from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from collections.abc import Iterator
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import settings
from app.models.regulation import RegulationCreationDraft, RegulationCreationMessage
from app.schemas.regulation import (
    RegulationCreationMessage as CreationMessageSchema,
    RegulationCreationSendRequest,
    RegulationCreationSession,
    RegulationParseResult,
)
from app.services.regulation import RegulationError, parse_upload
from app.services.regulation_creation.cursor_agent import (
    CursorAgentError,
    archive_agent,
    cancel_run,
    create_agent,
    create_run,
    stream_run_events,
    wait_for_run,
)
from app.services.regulation_creation.style_profile import build_style_profile


FIRST_QUESTION = "Напишите, для каких должностей создается регламент"
INTERVIEW_GUIDANCE = (
    "В режиме need_more не засыпай пользователя цепочкой открытых вопросов. "
    "Каждый следующий шаг формулируй так: 1) один конкретный вопрос; "
    "2) предполагаемый ответ, который ты сам выводишь из истории и типовой логики регламента; "
    "3) короткий вопрос 'Оставить это или переделать?'. "
    "В поле message пиши в понятном виде: 'Вопрос: ...\\n\\nПредлагаю так: ...\\n\\nОставить это или переделать?'. "
    "В поле quickAnswers для need_more всегда возвращай ['Оставить', 'Переделать']; "
    "если уместно, добавь третий краткий вариант с готовым альтернативным ответом. "
    "Если пользователь пишет 'Оставить', считай предложенный ответ подтверждённым и переходи дальше. "
    "Если пользователь пишет 'Переделать', попроси новую формулировку только для этого пункта."
)
FORCE_CREATE_GUIDANCE = (
    "Если пользователь просит создать регламент принудительно, не задавай новых вопросов. "
    "Сформируй status='ready' и document по текущей истории. "
    "Недостающие сведения заполняй аккуратными типовыми формулировками и явно помечай как предположение."
)


class RegulationCreationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def start_creation_session(db: Session, *, user_id: str) -> RegulationCreationSession:
    draft = RegulationCreationDraft(
        id=f"reg-create-{uuid4().hex[:12]}",
        user_id=user_id,
        status="collecting_positions",
        style_profile_json=build_style_profile(db, user_id=user_id),
    )
    db.add(draft)
    db.flush()
    _add_message(db, draft=draft, role="assistant", content=FIRST_QUESTION)
    db.commit()
    db.refresh(draft)
    return _session(db, draft)


def get_creation_session(db: Session, *, user_id: str, draft_id: str) -> RegulationCreationSession:
    return _session(db, _get_draft(db, user_id=user_id, draft_id=draft_id))


def terminate_active_creation_sessions(db: Session, *, user_id: str) -> dict:
    drafts = (
        db.query(RegulationCreationDraft)
        .filter(
            RegulationCreationDraft.user_id == user_id,
            RegulationCreationDraft.status.in_(["collecting_positions", "interview", "generating", "error"]),
        )
        .all()
    )
    closed = 0
    errors: list[str] = []
    for draft in drafts:
        if draft.cursor_agent_id:
            if draft.latest_run_id:
                try:
                    cancel_run(draft.cursor_agent_id, draft.latest_run_id)
                except CursorAgentError as exc:
                    if exc.status_code != 409:
                        errors.append(exc.message)
            try:
                archive_agent(draft.cursor_agent_id)
            except CursorAgentError as exc:
                errors.append(exc.message)
        draft.status = "closed"
        db.add(draft)
        closed += 1
    db.commit()
    return {"closed": closed, "errors": errors}


def send_creation_message(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    request: RegulationCreationSendRequest,
) -> RegulationCreationSession:
    message = request.message.strip()
    if not message:
        raise RegulationCreationError("Введите сообщение")
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if draft.status == "finalized":
        return _session(db, draft)
    _add_message(db, draft=draft, role="user", content=message)
    draft.status = "generating"
    db.add(draft)
    db.commit()

    history = _messages_for_draft(db, draft.id)
    prompt = _initial_prompt(draft, message) if not draft.cursor_agent_id else _followup_prompt(history, message)
    try:
        if not draft.cursor_agent_id:
            agent_id, run_id = create_agent(prompt)
            draft.cursor_agent_id = agent_id
            draft.latest_run_id = run_id
        else:
            run_id = create_run(draft.cursor_agent_id, prompt)
            draft.latest_run_id = run_id
        db.add(draft)
        db.commit()
        run = wait_for_run(draft.cursor_agent_id, draft.latest_run_id)
    except CursorAgentError as exc:
        draft.status = "error"
        db.add(draft)
        db.commit()
        raise RegulationCreationError(exc.message, status_code=exc.status_code) from exc

    _apply_agent_reply(db, user_id=user_id, draft=draft, raw=str(run.get("result") or ""))
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _session(db, draft)


def stream_creation_message(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    request: RegulationCreationSendRequest,
) -> Iterator[dict]:
    message = request.message.strip()
    if not message:
        raise RegulationCreationError("Введите сообщение")
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if draft.status == "finalized":
        yield {"type": "session", "session": _session(db, draft).model_dump(mode="json")}
        return

    _add_message(db, draft=draft, role="user", content=message)
    draft.status = "generating"
    db.add(draft)
    db.commit()
    yield {"type": "status", "status": "generating"}

    history = _messages_for_draft(db, draft.id)
    prompt = _initial_prompt(draft, message) if not draft.cursor_agent_id else _followup_prompt(history, message)
    final_text = ""
    try:
        if not draft.cursor_agent_id:
            agent_id, run_id = create_agent(prompt)
            draft.cursor_agent_id = agent_id
            draft.latest_run_id = run_id
        else:
            run_id = create_run(draft.cursor_agent_id, prompt)
            draft.latest_run_id = run_id
        db.add(draft)
        db.commit()
        try:
            for event in stream_run_events(draft.cursor_agent_id, draft.latest_run_id):
                event_type = str(event.get("event") or "")
                data = event.get("data") if isinstance(event.get("data"), dict) else {}
                if event_type == "thinking":
                    text = str(data.get("text") or "")
                    if text:
                        yield {"type": "thinking", "text": text}
                elif event_type == "assistant":
                    text = str(data.get("text") or "")
                    if text:
                        yield {"type": "assistant", "text": text}
                elif event_type == "result":
                    final_text = str(data.get("text") or "")
                    status = str(data.get("status") or "")
                    if status and status != "FINISHED":
                        raise CursorAgentError(f"Cursor Agent завершился со статусом {status}", status_code=502)
        except CursorAgentError as exc:
            if exc.status_code != 409 and "stream_unavailable" not in exc.message:
                raise
            yield {"type": "status", "status": "stream_unavailable_polling"}
    except CursorAgentError as exc:
        draft.status = "error"
        db.add(draft)
        db.commit()
        yield {"type": "error", "message": exc.message}
        return

    if not final_text:
        try:
            final_text = str(wait_for_run(draft.cursor_agent_id, draft.latest_run_id).get("result") or "")
        except CursorAgentError as exc:
            draft.status = "error"
            db.add(draft)
            db.commit()
            yield {"type": "error", "message": exc.message}
            return

    _apply_agent_reply(db, user_id=user_id, draft=draft, raw=final_text)
    db.commit()
    db.refresh(draft)
    yield {"type": "session", "session": _session(db, draft).model_dump(mode="json")}


def _apply_agent_reply(db: Session, *, user_id: str, draft: RegulationCreationDraft, raw: str) -> None:
    raw = raw.strip()
    parsed = _parse_agent_response(raw)
    if parsed.get("status") == "ready" and isinstance(parsed.get("document"), dict):
        try:
            result = _finalize_document(db, user_id=user_id, draft=draft, document=parsed["document"])
        except RegulationError as exc:
            draft.status = "error"
            db.add(draft)
            db.commit()
            raise RegulationCreationError(exc.message, status_code=exc.status_code) from exc
        except RegulationCreationError:
            draft.status = "error"
            db.add(draft)
            db.commit()
            raise
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content=parsed.get("message") or "Регламент сформирован. Проверьте документ перед созданием агента.",
            structured={"resultRegulationId": result.regulationId},
        )
        draft.status = "finalized"
        draft.result_regulation_id = result.regulationId
    else:
        quick_answers = parsed.get("quickAnswers") or ["Оставить", "Переделать"]
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content=parsed.get("message") or raw or "Уточните, пожалуйста, детали процесса.",
            structured={"quickAnswers": quick_answers},
        )
        draft.status = "interview"
        if positions := parsed.get("positions"):
            draft.positions_json = [str(item) for item in positions if str(item).strip()]


def _finalize_document(
    db: Session,
    *,
    user_id: str,
    draft: RegulationCreationDraft,
    document: dict,
) -> RegulationParseResult:
    output_dir = settings.regulation_storage_dir / "created" / draft.id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _safe_filename(str(document.get("title") or "created-regulation")) 
    path = path.with_suffix(".docx")
    _write_docx(path, document)
    result = parse_upload(
        db,
        user_id=user_id,
        filename=path.name,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        data=path.read_bytes(),
    )
    draft.result_document_path = str(path)
    draft.draft_document_json = document
    return result


def _write_docx(path: Path, document: dict) -> None:
    try:
        from docx import Document
    except ImportError as exc:
        raise RegulationCreationError("Для создания DOCX требуется python-docx", status_code=500) from exc
    doc = Document()
    title = str(document.get("title") or "Регламент")
    doc.add_heading(title, level=1)
    for section in document.get("sections") or []:
        if not isinstance(section, dict):
            continue
        heading = str(section.get("title") or "").strip()
        number = str(section.get("number") or "").strip()
        if heading:
            doc.add_heading(f"{number} {heading}".strip(), level=2)
        for paragraph in section.get("paragraphs") or []:
            text = str(paragraph or "").strip()
            if text:
                doc.add_paragraph(text)
        for item in section.get("items") or []:
            text = str(item or "").strip()
            if text:
                doc.add_paragraph(text, style="List Bullet")
    doc.save(str(path))


def _initial_prompt(draft: RegulationCreationDraft, positions_message: str) -> str:
    return (
        "Ты помогаешь создать регламент на русском языке в деловом стиле. "
        "Файлы существующих регламентов тебе не передаются и не должны запрашиваться. "
        "Backend заранее проанализировал их локально и передаёт только обобщённые правила стилизации. "
        "Веди интервью: сначала извлеки должности из ответа пользователя, затем по каждой должности выясняй функции, "
        "условия запуска, входы/выходы, сроки, исключения, согласования, системы и ответственность. "
        "Если сведений недостаточно, задай один конкретный следующий вопрос. "
        f"{INTERVIEW_GUIDANCE} "
        f"{FORCE_CREATE_GUIDANCE} "
        "Когда данных достаточно, верни JSON с status='ready' и document. "
        "Всегда отвечай строго JSON без markdown: "
        '{"status":"need_more|ready","message":"...","positions":[],"quickAnswers":[],"document":{"title":"","sections":[{"number":"1","title":"","paragraphs":[],"items":[]}]}}.\n'
        f"Обобщённый профиль стилизации без текста исходных документов: {json.dumps(draft.style_profile_json, ensure_ascii=False)}\n"
        f"Ответ пользователя о должностях: {positions_message}"
    )


def _followup_prompt(history_items: list[RegulationCreationMessage], message: str) -> str:
    history = [
        {"role": item.role, "content": item.content}
        for item in history_items
    ][-20:]
    return (
        "Продолжай интервью для создания регламента. Используй историю и новый ответ пользователя. "
        "Не запрашивай и не ожидай файлы существующих регламентов: применяй только уже переданные обобщённые правила стилизации. "
        "Если информации мало, задай следующий точный вопрос. Если достаточно, сформируй document. "
        f"{INTERVIEW_GUIDANCE} "
        f"{FORCE_CREATE_GUIDANCE} "
        "Отвечай строго JSON без markdown: "
        '{"status":"need_more|ready","message":"...","positions":[],"quickAnswers":[],"document":{"title":"","sections":[{"number":"1","title":"","paragraphs":[],"items":[]}]}}.\n'
        f"История: {json.dumps(history, ensure_ascii=False)}\n"
        f"Новый ответ пользователя: {message}"
    )


def _parse_agent_response(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"status": "need_more", "message": raw}
    except json.JSONDecodeError:
        try:
            data = ast.literal_eval(text)
            return data if isinstance(data, dict) else {"status": "need_more", "message": raw}
        except (SyntaxError, ValueError):
            pass
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            try:
                data = json.loads(match.group(0))
                return data if isinstance(data, dict) else {"status": "need_more", "message": raw}
            except json.JSONDecodeError:
                try:
                    data = ast.literal_eval(match.group(0))
                    return data if isinstance(data, dict) else {"status": "need_more", "message": raw}
                except (SyntaxError, ValueError):
                    pass
    return {"status": "need_more", "message": raw}


def _session(db: Session, draft: RegulationCreationDraft) -> RegulationCreationSession:
    result = None
    if draft.result_regulation_id:
        from app.services.regulation.storage import get_document

        doc = get_document(db, regulation_id=draft.result_regulation_id, user_id=draft.user_id)
        if doc is not None:
            result = RegulationParseResult.model_validate(doc.result_json)
    return RegulationCreationSession(
        draftId=draft.id,
        status=draft.status,
        cursorAgentId=draft.cursor_agent_id,
        latestRunId=draft.latest_run_id,
        positions=[str(item) for item in draft.positions_json or []],
        messages=[
            CreationMessageSchema(
                messageId=item.id,
                draftId=item.draft_id,
                role=item.role,
                content=item.content,
                structured=item.structured_json or {},
                createdAt=item.created_at,
            )
            for item in _messages_for_draft(db, draft.id)
        ],
        resultRegulation=result,
        resultDocumentPath=draft.result_document_path,
        createdAt=draft.created_at,
        updatedAt=draft.updated_at,
    )


def _messages_for_draft(db: Session, draft_id: str) -> list[RegulationCreationMessage]:
    return (
        db.query(RegulationCreationMessage)
        .filter(RegulationCreationMessage.draft_id == draft_id)
        .order_by(RegulationCreationMessage.created_at.asc())
        .all()
    )


def _add_message(
    db: Session,
    *,
    draft: RegulationCreationDraft,
    role: str,
    content: str,
    structured: dict | None = None,
) -> None:
    db.add(
        RegulationCreationMessage(
            id=f"reg-create-msg-{uuid4().hex[:12]}",
            draft_id=draft.id,
            user_id=draft.user_id,
            role=role,
            content=content,
            structured_json=structured or {},
        )
    )


def _get_draft(db: Session, *, user_id: str, draft_id: str) -> RegulationCreationDraft:
    draft = (
        db.query(RegulationCreationDraft)
        .filter(RegulationCreationDraft.id == draft_id, RegulationCreationDraft.user_id == user_id)
        .first()
    )
    if draft is None:
        raise RegulationCreationError("Черновик создания регламента не найден", status_code=404)
    return draft


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-zА-Яа-яЁё0-9._ -]+", " ", value).strip()
    return (safe or "created-regulation")[:120]
