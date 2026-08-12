from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.regulation import (
    AgentDraft,
    QuestionChatMessage,
    QuestionChatSession,
    ReadinessRun,
    RegulationDocument,
)
from app.schemas.regulation import (
    AgentReadinessResult,
    QuestionChatMessageResult,
    QuestionChatSendRequest,
    QuestionChatSessionResult,
    ReadinessAnswerRequest,
    ReadinessQuestion,
    RegulationParseResult,
)
from app.services.agents import sync_draft_progress
from app.services.readiness.service import ReadinessError, answer_readiness_question


def create_or_get_question_chat(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    question_id: str,
) -> QuestionChatSessionResult:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    readiness = _get_readiness(db, draft)
    question = next((item for item in readiness.questions if item.questionId == question_id), None)
    if question is None:
        raise ReadinessError("Вопрос не найден", status_code=404)
    session = (
        db.query(QuestionChatSession)
        .filter(QuestionChatSession.draft_id == draft_id, QuestionChatSession.question_id == question_id)
        .first()
    )
    if session is None:
        context = _context(db, draft, readiness, question_id)
        session = QuestionChatSession(
            id=f"qchat-{uuid4().hex[:12]}",
            draft_id=draft_id,
            readiness_run_id=draft.readiness_run_id,
            question_id=question_id,
            function_id=question.functionId,
            target_field=question.targetField,
            status="answered" if question.answered else "active",
            context_json=context,
        )
        db.add(session)
        db.flush()
        db.add(
            QuestionChatMessage(
                id=f"qmsg-{uuid4().hex[:12]}",
                session_id=session.id,
                role="assistant",
                content=_initial_prompt(context),
                structured_json={},
            )
        )
        db.commit()
        db.refresh(session)
    return _session_result(db, session)


def get_question_chat(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    question_id: str,
) -> QuestionChatSessionResult:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    session = (
        db.query(QuestionChatSession)
        .filter(
            QuestionChatSession.draft_id == draft.id,
            QuestionChatSession.question_id == question_id,
        )
        .first()
    )
    if session is None:
        return create_or_get_question_chat(db, user_id=user_id, draft_id=draft_id, question_id=question_id)
    return _session_result(db, session)


def send_question_chat_message(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    question_id: str,
    request: QuestionChatSendRequest,
) -> QuestionChatSessionResult:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    session = db.query(QuestionChatSession).filter(
        QuestionChatSession.draft_id == draft_id,
        QuestionChatSession.question_id == question_id,
    ).first()
    if session is None:
        create_or_get_question_chat(db, user_id=user_id, draft_id=draft_id, question_id=question_id)
        session = db.query(QuestionChatSession).filter(
            QuestionChatSession.draft_id == draft_id,
            QuestionChatSession.question_id == question_id,
        ).first()
    assert session is not None
    user_text = request.message.strip()
    db.add(
        QuestionChatMessage(
            id=f"qmsg-{uuid4().hex[:12]}",
            session_id=session.id,
            role="user",
            content=user_text,
            structured_json={},
        )
    )
    readiness = _get_readiness(db, draft)
    structured = _extract_structured_answer(user_text, session.context_json, readiness)
    if structured["isComplete"]:
        applied = []
        for item in structured["relatedAnswers"]:
            readiness = answer_readiness_question(
                db,
                user_id=user_id,
                regulation_id=draft.regulation_id,
                readiness_run_id=draft.readiness_run_id,
                request=ReadinessAnswerRequest(
                    questionId=str(item["questionId"]),
                    answer=str(item["answer"]),
                ),
            )
            applied.append(item)
        readiness = _reprioritize_questions(
            db,
            user_id=user_id,
            regulation_id=draft.regulation_id,
            readiness_run_id=draft.readiness_run_id,
            answer=user_text,
        )
        sync_draft_progress(db, draft_id=draft.id, readiness=readiness)
        session.status = "answered"
        assistant_text = _accepted_answer_text(applied)
    else:
        session.status = "needs_clarification"
        assistant_text = str(structured.get("followUpQuestion") or _follow_up_prompt(session.context_json))
    db.add(
        QuestionChatMessage(
            id=f"qmsg-{uuid4().hex[:12]}",
            session_id=session.id,
            role="assistant",
            content=assistant_text,
            structured_json=structured,
        )
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_result(db, session)


def _get_draft(db: Session, *, user_id: str, draft_id: str) -> AgentDraft:
    draft = db.query(AgentDraft).filter(AgentDraft.id == draft_id, AgentDraft.user_id == user_id).first()
    if draft is None:
        raise ReadinessError("Черновик агента не найден", status_code=404)
    if not draft.readiness_run_id:
        raise ReadinessError("Для черновика ещё не создана проверка готовности", status_code=409)
    return draft


def _get_readiness(db: Session, draft: AgentDraft) -> AgentReadinessResult:
    run = db.query(ReadinessRun).filter(ReadinessRun.id == draft.readiness_run_id).first()
    if run is None:
        raise ReadinessError("Проверка готовности не найдена", status_code=404)
    return AgentReadinessResult.model_validate(run.result_json)


def _context(db: Session, draft: AgentDraft, readiness: AgentReadinessResult, question_id: str) -> dict:
    doc = db.query(RegulationDocument).filter(RegulationDocument.id == draft.regulation_id).first()
    result = RegulationParseResult.model_validate(doc.result_json) if doc is not None else None
    question = next(item for item in readiness.questions if item.questionId == question_id)
    function = next((item for item in readiness.functions if item.functionId == question.functionId), None)
    fragments = {fragment.fragmentId: fragment for fragment in (result.fragments if result else [])}
    blocks = []
    for block_id in question.affectedBlocks:
        fragment = fragments.get(block_id)
        if fragment is not None:
            blocks.append({"blockId": fragment.fragmentId, "section": fragment.section, "text": fragment.text})
    return {
        "question": question.model_dump(mode="json"),
        "function": function.model_dump(mode="json") if function is not None else {},
        "affectedBlocks": blocks,
        "draft": {"title": draft.title, "position": draft.position, "department": draft.department},
    }


def _initial_prompt(context: dict) -> str:
    question = context.get("question") or {}
    blocks = context.get("affectedBlocks") or []
    quote = blocks[0]["text"] if blocks else question.get("sourceEvidence", {}).get("quote", "")
    return (
        f"{question.get('question', 'Нужно уточнение по регламенту')}\n\n"
        f"Зачем спрашиваю: {question.get('reason', '')}\n\n"
        f"Связанный фрагмент регламента: «{quote[:700]}»\n\n"
        "Ответьте своими словами. Если информации пока нет, так и напишите."
    )


def _follow_up_prompt(context: dict) -> str:
    field = (context.get("question") or {}).get("targetField", "параметр")
    return (
        f"Ответ пока недостаточно конкретный для поля «{field}». "
        "Уточните, пожалуйста, конкретное правило, срок, роль или действие, которое нужно внести в регламент."
    )


def _extract_structured_answer(text: str, context: dict, readiness: AgentReadinessResult) -> dict:
    clean = text.strip()
    current = context.get("question") or {}
    incomplete = _needs_clarification(clean)
    related_answers = []
    if not incomplete:
        related_answers.append(
            {
                "questionId": current.get("questionId", ""),
                "targetField": current.get("targetField", ""),
                "answer": clean,
            }
        )
        related_answers.extend(_related_answers(clean, current, readiness))
    return {
        "isComplete": not incomplete,
        "targetField": (context.get("question") or {}).get("targetField", ""),
        "answer": clean,
        "relatedAnswers": related_answers,
        "confidence": 0.9 if not incomplete else 0.2,
        "needsFollowUp": incomplete,
        "followUpQuestion": _follow_up_from_answer(clean, context) if incomplete else "",
        "proposedChangeHint": "Добавить уточнение к связанному блоку регламента" if not incomplete else "",
    }


def _needs_clarification(text: str) -> bool:
    clean = text.strip().casefold()
    if not clean or clean in {"не знаю", "пока неизвестно", "позже", "уточню позже"}:
        return True
    vague = {"по ситуации", "как обычно", "на усмотрение", "пока непонятно"}
    return clean in vague or (len(clean) < 6 and clean not in {"да", "нет"})


def _related_answers(text: str, current: dict, readiness: AgentReadinessResult) -> list[dict]:
    current_question_id = str(current.get("questionId") or "")
    current_function_id = str(current.get("functionId") or "")
    out = []
    for question in readiness.questions:
        if question.answered or question.questionId == current_question_id:
            continue
        if current_function_id and question.functionId != current_function_id:
            continue
        if _answer_mentions_field(text, question.targetField):
            out.append(
                {
                    "questionId": question.questionId,
                    "targetField": question.targetField,
                    "answer": text.strip(),
                }
            )
    return out


def _answer_mentions_field(text: str, field: str) -> bool:
    clean = text.casefold()
    signals = {
        "trigger": ("когда", "после", "при ", "по поручению", "график", "появлен"),
        "deadline": ("срок", "день", "час", "минут", "недел", "рабоч"),
        "errors": ("ошиб", "сбой", "невозмож", "не получится", "отказ"),
        "escalation": ("эскал", "переда", "руковод", "начальник"),
        "recipient": ("переда", "кому", "получател", "руковод"),
        "approval": ("подтверд", "соглас", "утвержд", "одобр"),
        "inputs": ("данн", "документ", "файл", "заявк", "информац", "вход"),
        "system": ("систем", "crm", "erp", "битрикс", "1с"),
        "result": ("результ", "отчет", "отчёт", "сформир", "готов"),
        "control": ("контрол", "провер", "монитор"),
        "conditions": ("если", "услов", "случа"),
        "branches": ("если", "иначе", "вариант", "или"),
        "permissions": ("доступ", "прав", "учетн", "учётн"),
        "restrictions": ("нельзя", "запрет", "огранич"),
        "kpi": ("kpi", "метрик", "показател"),
    }
    return any(signal in clean for signal in signals.get(field, ()))


def _reprioritize_questions(
    db: Session,
    *,
    user_id: str,
    regulation_id: str,
    readiness_run_id: str,
    answer: str,
) -> AgentReadinessResult:
    run = db.query(ReadinessRun).filter(
        ReadinessRun.id == readiness_run_id,
        ReadinessRun.user_id == user_id,
        ReadinessRun.regulation_id == regulation_id,
    ).first()
    if run is None:
        raise ReadinessError("Проверка готовности не найдена", status_code=404)
    readiness = AgentReadinessResult.model_validate(run.result_json)
    priorities = _field_priorities_from_answer(answer)
    readiness.questions = sorted(
        readiness.questions,
        key=lambda item: (
            1 if item.answered else 0,
            priorities.get(item.targetField, 10),
            _severity_rank(item.severity),
            item.questionId,
        ),
    )
    run.result_json = readiness.model_dump(mode="json")
    db.add(run)
    db.commit()
    db.refresh(run)
    return AgentReadinessResult.model_validate(run.result_json)


def _field_priorities_from_answer(answer: str) -> dict[str, int]:
    clean = answer.casefold()
    priorities: dict[str, int] = {}
    if any(token in clean for token in ("если", "иначе", "ошиб", "сбой", "невозможно")):
        priorities.update({"errors": 0, "branches": 1, "conditions": 2})
    if any(token in clean for token in ("руковод", "соглас", "подтверд", "переда")):
        priorities.update({"approval": 0, "escalation": 1, "recipient": 2})
    if any(token in clean for token in ("срок", "день", "час", "минут")):
        priorities["deadline"] = 0
    return priorities


def _severity_rank(severity: str) -> int:
    return {"blocking": 0, "important": 1, "optional": 2}.get(severity, 3)


def _accepted_answer_text(applied: list[dict]) -> str:
    if len(applied) <= 1:
        return "Понял. Я предлагаю дополнить пункт регламента так:"
    return f"Понял. Этот ответ закрывает сразу {len(applied)} уточнения. Я подготовил проекты изменений регламента."


def _follow_up_from_answer(text: str, context: dict) -> str:
    question = context.get("question") or {}
    if text.strip().casefold() == "пока неизвестно":
        return "Понял. Тогда уточните, кто сможет определить это правило и когда к нему можно вернуться?"
    return (
        "Пока не хватает конкретики. Опишите правило так, как оно должно попасть в регламент: "
        "когда начинается действие, кто отвечает, какой результат ожидается или что делать при исключении."
    )


def _session_result(db: Session, session: QuestionChatSession) -> QuestionChatSessionResult:
    messages = (
        db.query(QuestionChatMessage)
        .filter(QuestionChatMessage.session_id == session.id)
        .order_by(QuestionChatMessage.created_at.asc())
        .all()
    )
    return QuestionChatSessionResult(
        sessionId=session.id,
        draftId=session.draft_id,
        readinessRunId=session.readiness_run_id,
        questionId=session.question_id,
        functionId=session.function_id,
        targetField=session.target_field,
        status=session.status,
        context=session.context_json,
        messages=[
            QuestionChatMessageResult(
                messageId=message.id,
                sessionId=message.session_id,
                role=message.role,
                content=message.content,
                structured=message.structured_json,
                createdAt=message.created_at,
            )
            for message in messages
        ],
    )
