from __future__ import annotations

import ast
import json
import logging
import re
import tempfile
import time
from time import perf_counter
from pathlib import Path
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.config import BACKEND_ROOT, settings
from app.models.regulation import (
    RegulationCreationDraft,
    RegulationCreationMessage,
    RegulationDocument,
)
from app.models.user import AppUser
from app.schemas.regulation import (
    RegulationCreationApplyRequest,
    RegulationCreationMessage as CreationMessageSchema,
    RegulationCreationSendRequest,
    RegulationCreationSession,
    RegulationCreationTurn,
    RegulationFragment,
    RegulationParseResult,
)
from app.services.regulation import RegulationError
from app.services.regulation.storage import new_regulation_id, save_upload
from app.services.regulation_creation.cursor_agent import (
    CursorAgentError,
    archive_agent,
    cancel_run,
    create_agent,
    create_run,
    stream_run_events,
    wait_for_run,
)
from app.services.regulation.full_text import compose_regulation_text
from app.services.regulation.detect import is_scan_pdf
from app.services.regulation.pdf_ocr import extract_pdf_scan
from app.services.regulation_creation.interview import (
    append_user_turn,
    build_creation_prompt,
    build_followup_creation_prompt,
    creation_interviewer_rules,
    creation_system_rules,
    current_interview_process_id,
    document_from_interview,
    document_has_body,
    document_has_full_text,
    interview_progress,
    interview_sdk_agent_id,
    interview_snapshot,
    interview_write_document,
    interview_use_tools,
    leading_question_text,
    is_process_select_message,
    is_replacement_garbage,
    merge_agent_payload,
    question_for_selected_processes,
    selected_process_ids,
    new_interview_state,
    normalize_interview_state,
    normalize_process_id,
    ready_blocker,
    remember_assistant_question,
    set_interview_position,
    set_sdk_agent_id,
    set_research_sdk_agent_id,
    research_sdk_agent_id,
    _clean_str,
)
from app.services.regulation_creation.pipeline import (
    apply_round_answers,
    ensure_process_selection_state,
    has_process_candidates,
    incremental_document_from_state,
    normalize_pipeline,
    pending_interview_work,
    processes_need_collect_questions,
    resume_interview_if_pending,
    select_processes as pipeline_select_processes,
    set_pipeline_stage,
    slice_materials_for_prompt,
    sync_remaining_estimate,
    _drop_known_questions,
    _filter_round_questions,
)
from app.services.regulation_creation.dual_workflow import (
    apply_material_review,
    apply_research_payload,
    build_material_review_prompt,
    build_research_prefetch_prompt,
    completeness_report_markdown,
    dual_workflow_enabled,
    enable_dual_workflow,
    merge_agent_candidates_from_payload,
    processes_ready_for_agent,
    spawn_regulation_process_agents,
)
from app.services.regulation_creation.question_queue import (
    FULL_QUEUE_TARGET,
    MIN_QUEUE_DEPTH,
    TARGET_QUEUE_DEPTH,
    build_fastpath_reply_from_queue,
    consume_queue_head,
    enqueue_round_batch,
    needs_llm_prefetch,
    peek_queue_head,
    queue_depth,
    queue_snapshot,
    queued_question_metadata,
    replenish_queue,
    _has_open_current_question,
)
from app.services.regulation_creation.sto_template import STO_TEMPLATE_PATH, fill_sto_regulation
from app.services.regulation_creation.template_tools import (
    load_structure_json,
    markdown_to_docx,
    validate_regulation_markdown,
)
from app.services.workflows.document import DocumentError, load_attachment_bytes

_CREATION_ATTACH_SUFFIXES = {".doc", ".docx", ".pdf", ".md", ".txt"}
_MAX_ATTACH_CHARS = 60_000
_MAX_ATTACH_PROMPT_CHARS = 32_000
_MESSAGE_CONTENT_LIMIT = 7900
logger = logging.getLogger(__name__)
_REGULATION_TEMPLATE_STRUCTURE_PATH = BACKEND_ROOT / "app" / "static" / "sto_regulation_structure.json"
_REGULATION_RULES_VERSION = "1.0"
_creation_template_structure_cache: dict[str, Any] | None = None


FIRST_QUESTION = (
    "Приложите один или несколько файлов с обязанностями/процессами или коротко напишите должность "
    "и функции пользователя. Я разберу документы и буду уточнять каждый пробел по одному."
)
class RegulationCreationError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


OPEN_CREATION_STATUSES = ("collecting_positions", "interview", "generating", "error")


def get_active_creation_session(db: Session, *, user_id: str) -> RegulationCreationSession | None:
    draft = (
        db.query(RegulationCreationDraft)
        .filter(
            RegulationCreationDraft.user_id == user_id,
            RegulationCreationDraft.status.in_(list(OPEN_CREATION_STATUSES)),
        )
        .order_by(RegulationCreationDraft.updated_at.desc())
        .first()
    )
    if draft is None:
        return None
    return _session(db, draft)


def start_creation_session(
    db: Session,
    *,
    user_id: str,
    fresh: bool = False,
) -> RegulationCreationSession:
    if not fresh:
        existing = get_active_creation_session(db, user_id=user_id)
        if existing is not None:
            return existing
    else:
        terminate_active_creation_sessions(db, user_id=user_id)

    user = db.get(AppUser, user_id)
    interview = enable_dual_workflow(
        set_interview_position(new_interview_state(), getattr(user, "position", "") or "")
    )
    draft = RegulationCreationDraft(
        id=f"reg-create-{uuid4().hex[:12]}",
        user_id=user_id,
        status="collecting_positions",
        style_profile_json={},
        interview_json=interview,
    )
    db.add(draft)
    db.flush()
    _add_message(db, draft=draft, role="assistant", content=FIRST_QUESTION)
    db.commit()
    db.refresh(draft)
    return _session(db, draft)


def get_creation_session(db: Session, *, user_id: str, draft_id: str) -> RegulationCreationSession:
    return _session(db, _get_draft(db, user_id=user_id, draft_id=draft_id))


def peek_creation_turn(db: Session, *, user_id: str, draft_id: str) -> RegulationCreationTurn:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    last_user = ""
    for item in reversed(_messages_for_draft(db, draft.id)):
        if item.role == "user":
            last_user = item.content or ""
            break
    return _turn_payload(
        db,
        draft,
        message=last_user,
        force_create=_is_force_create_message(last_user),
        new_attachments=False,
    )


def advance_creation_question(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
) -> RegulationCreationSession:
    """Serve the next deterministic collect question when the UI is waiting."""
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if draft.status == "finalized":
        return _session(db, draft)
    interview = normalize_interview_state(draft.interview_json)
    interview = resume_interview_if_pending(interview)
    draft.interview_json = interview
    if pending_interview_work(interview) and _has_open_current_question(interview):
        current = interview.get("currentQuestion") if isinstance(interview.get("currentQuestion"), dict) else {}
        if not _clean_str(current.get("answer")):
            interview.pop("currentQuestion", None)
            draft.interview_json = interview
    if _has_open_current_question(interview):
        draft.interview_json = interview
        db.add(draft)
        db.commit()
        return _session(db, draft)
    interview.pop("currentQuestion", None)
    interview = replenish_queue(interview, target=FULL_QUEUE_TARGET)
    if isinstance(interview, dict):
        interview = {**interview, "pipeline": sync_remaining_estimate(interview)}
    draft.interview_json = interview
    pipeline = normalize_pipeline(interview.get("pipeline"))
    head = peek_queue_head(interview)
    messages = _messages_for_draft(db, draft.id)
    last_msg = messages[-1] if messages else None
    last_assistant = next((item for item in reversed(messages) if item.role == "assistant"), None)
    head_text = str((head or {}).get("text") or "").strip()
    if (
        last_assistant
        and head_text
        and (last_assistant.content or "").strip() == head_text
        and last_msg
        and last_msg.role == "assistant"
    ):
        draft.status = "interview"
        db.add(draft)
        db.commit()
        db.refresh(draft)
        return _session(db, draft)
    if (
        last_assistant
        and head_text
        and (last_assistant.content or "").strip() == head_text
        and last_msg
        and last_msg.role == "user"
        and head
    ):
        interview = consume_queue_head(interview, question_id=str(head.get("id") or ""))
        interview = replenish_queue(interview, target=FULL_QUEUE_TARGET)
        draft.interview_json = interview
        head = peek_queue_head(interview)
        if head:
            _post_queued_question_message(
                db,
                draft=draft,
                parsed={"status": "need_more"},
                head=head,
                force_post=True,
            )
        draft.status = "interview"
        db.add(draft)
        db.commit()
        db.refresh(draft)
        return _session(db, draft)
    if head and (pipeline.get("selectedProcessIds") or []) and pending_interview_work(interview):
        _post_queued_question_message(
            db,
            draft=draft,
            parsed={"status": "need_more"},
            head=head,
            force_post=True,
        )
    draft.status = "interview"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _session(db, draft)


def get_creation_document(db: Session, *, user_id: str, draft_id: str) -> Path:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    path = Path(draft.result_document_path or "")
    if path.is_file():
        return path
    if draft.result_regulation_id:
        from app.services.regulation.storage import get_document

        doc = get_document(db, regulation_id=draft.result_regulation_id, user_id=user_id)
        stored = Path((doc.storage_path if doc is not None else "") or "")
        if stored.is_file():
            return stored
    rebuilt = _rebuild_creation_docx(draft)
    if rebuilt is not None and rebuilt.is_file():
        draft.result_document_path = str(rebuilt)
        db.add(draft)
        db.commit()
        return rebuilt
    raise RegulationCreationError("Файл регламента ещё не создан", status_code=404)


def _rebuild_creation_docx(draft: RegulationCreationDraft) -> Path | None:
    document = draft.draft_document_json if isinstance(draft.draft_document_json, dict) else {}
    if not document_has_body(document):
        title = str((document or {}).get("title") or "").strip()
        document = document_from_interview(draft.interview_json, title)
    if not document_has_body(document):
        return None
    output_dir = settings.regulation_storage_dir / "created" / draft.id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _safe_filename(str(document.get("title") or "created-regulation"))
    path = path.with_suffix(".docx")
    _write_docx(path, document)
    return path


def persist_creation_turn(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    request: RegulationCreationSendRequest,
    files: list[tuple[str, bytes]] | None = None,
) -> RegulationCreationTurn:
    attachments = _load_creation_attachments(files or [])
    message = request.message.strip()
    if not message and not attachments:
        raise RegulationCreationError("Введите сообщение или приложите файл")
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if draft.status == "finalized":
        return _turn_payload(db, draft, message="", force_create=False, new_attachments=False)
    force_create = _is_force_create_message(message)
    display_message = _display_user_message(message, attachments)
    existing_messages = _messages_for_draft(db, draft.id)
    if existing_messages and existing_messages[-1].role == "user":
        last_user = (existing_messages[-1].content or "").strip()
        if last_user == display_message.strip() and draft.status in {"generating", "interview"}:
            logger.info(
                "reg_create skip duplicate user message draft=%s status=%s",
                draft.id,
                draft.status,
            )
            turn = _turn_payload(db, draft, message=message, force_create=force_create)
            turn = _strip_duplicate_prefetch_turn(db, draft, turn)
            db.add(draft)
            db.commit()
            db.refresh(draft)
            return turn
    before_stage = normalize_pipeline(
        draft.interview_json.get("pipeline") if isinstance(draft.interview_json, dict) else {}
    ).get("stage")
    started = perf_counter()
    draft.interview_json = append_user_turn(draft.interview_json, message, attachments)
    after_stage = normalize_pipeline(
        draft.interview_json.get("pipeline") if isinstance(draft.interview_json, dict) else {}
    ).get("stage")
    logger.info(
        "reg_create timing extract/select phase_ms=%s draft=%s from=%s to=%s",
        int((perf_counter() - started) * 1000),
        draft.id,
        before_stage,
        after_stage,
    )
    _add_message(
        db,
        draft=draft,
        role="user",
        content=display_message,
        structured=_attachments_structured(attachments),
    )
    draft.status = "generating"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _turn_payload(
        db,
        draft,
        message=message,
        force_create=force_create,
        new_attachments=bool(attachments),
    )


def apply_creation_reply(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    request: RegulationCreationApplyRequest,
) -> RegulationCreationSession:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if draft.status == "finalized":
        return _session(db, draft)
    if request.sdkAgentId.strip():
        draft.interview_json = set_sdk_agent_id(draft.interview_json, request.sdkAgentId)
    force_create = bool(request.forceCreate)
    if request.researchOnly:
        _apply_research_reply(db, draft=draft, raw=request.answer, research_agent_id=request.sdkAgentId)
        draft.interview_json = resume_interview_if_pending(
            draft.interview_json if isinstance(draft.interview_json, dict) else {}
        )
        draft.interview_json = replenish_queue(
            normalize_interview_state(draft.interview_json),
            target=FULL_QUEUE_TARGET,
        )
        _ensure_queued_question_posted(db, draft)
    elif request.prefetchOnly:
        _apply_prefetch_reply(db, draft=draft, raw=request.answer)
        draft.interview_json = resume_interview_if_pending(
            draft.interview_json if isinstance(draft.interview_json, dict) else {}
        )
        draft.interview_json = replenish_queue(
            normalize_interview_state(draft.interview_json),
            target=FULL_QUEUE_TARGET,
        )
        _ensure_queued_question_posted(db, draft)
    else:
        _apply_agent_reply(
            db,
            user_id=user_id,
            draft=draft,
            raw=request.answer,
            force_create=force_create,
        )
        _ensure_queued_question_posted(db, draft)
        _autostart_assemble_when_ready(db, draft)
        _maybe_spawn_process_agents(db, user_id=user_id, draft=draft)
    draft.interview_json = resume_interview_if_pending(
        draft.interview_json if isinstance(draft.interview_json, dict) else {}
    )
    draft.interview_json = replenish_queue(
        normalize_interview_state(draft.interview_json),
        target=FULL_QUEUE_TARGET,
    )
    if isinstance(draft.interview_json, dict):
        draft.interview_json = {
            **draft.interview_json,
            "pipeline": sync_remaining_estimate(draft.interview_json),
        }
    if needs_llm_prefetch(draft.interview_json):
        draft.interview_json = {
            **normalize_interview_state(draft.interview_json),
            "prefetchInProgress": True,
        }
    draft.status = "interview"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _session(db, draft)


def _needs_research_prefetch(interview: dict[str, Any]) -> bool:
    """Background research — throttled to avoid parallel SDK overload."""
    if not dual_workflow_enabled(interview):
        return False
    pipeline = normalize_pipeline(interview.get("pipeline"))
    phase = str(pipeline.get("interviewPhase") or pipeline.get("stage") or "")
    if phase not in {"collect", "rounds"}:
        return False
    if not (pipeline.get("selectedProcessIds") or []):
        return False
    if queue_depth(interview) >= MIN_QUEUE_DEPTH:
        return False
    asked = int(pipeline.get("questionsAskedTotal") or 0)
    now = int(time.time())
    last_at = int(interview.get("researchPrefetchAt") or 0)
    last_asked = int(interview.get("researchPrefetchAtAsked") or -1)
    if asked == 0 and not interview.get("researchFacts"):
        return True
    if now - last_at < 90:
        return False
    if asked - last_asked >= 4:
        return True
    hypotheses = interview.get("researchQueue") if isinstance(interview.get("researchQueue"), list) else []
    pending = [item for item in hypotheses if isinstance(item, dict) and item.get("needsHumanConfirm")]
    return bool(pending) and asked - last_asked >= 2


def _turn_payload(
    db: Session,
    draft: RegulationCreationDraft,
    *,
    message: str,
    force_create: bool,
    new_attachments: bool = False,
) -> RegulationCreationTurn:
    timing_start = perf_counter()
    sdk_id = interview_sdk_agent_id(draft.interview_json)
    write_document = interview_write_document(draft.interview_json, force_create=force_create)
    use_tools = interview_use_tools(
        draft.interview_json,
        force_create=force_create,
        new_attachments=new_attachments,
    )
    if write_document:
        prompt = (
            build_followup_creation_prompt(
                message=message,
                force_create=force_create,
                state=draft.interview_json,
                write_document=True,
            )
            if sdk_id
            else build_creation_prompt(
                state=draft.interview_json,
                message=message,
                initial=True,
                force_create=force_create,
                include_attachment_bodies=False,
            )
        )
        rules = creation_system_rules(force_create=force_create)
    elif use_tools:
        prompt = build_creation_prompt(
            state=draft.interview_json,
            message=message,
            initial=not sdk_id,
            force_create=force_create,
            include_attachment_bodies=False,
        )
        rules = creation_system_rules(force_create=force_create)
    elif sdk_id:
        prompt = build_followup_creation_prompt(
            message=message,
            force_create=force_create,
            state=draft.interview_json,
            write_document=False,
        )
        rules = creation_interviewer_rules()
    else:
        prompt = build_creation_prompt(
            state=draft.interview_json,
            message=message,
            initial=True,
            force_create=force_create,
            include_attachment_bodies=True,
        )
        rules = creation_interviewer_rules()
    return RegulationCreationTurn(
        session=_session(db, draft),
        interview=interview_snapshot(draft.interview_json),
        sdkPrompt=prompt,
        sdkRules=rules,
        sdkAgentId=sdk_id,
        forceCreate=force_create,
        writeDocument=write_document,
        useTools=use_tools,
    )


def select_creation_processes(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    process_ids: list[str],
) -> RegulationCreationSession:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    try:
        draft.interview_json = pipeline_select_processes(draft.interview_json, process_ids)
    except ValueError as exc:
        raise RegulationCreationError(str(exc), status_code=400) from exc
    draft.interview_json = replenish_queue(
        normalize_interview_state(draft.interview_json),
        target=FULL_QUEUE_TARGET,
    )
    if isinstance(draft.interview_json, dict):
        draft.interview_json.pop("currentQuestion", None)
        draft.interview_json = {
            **draft.interview_json,
            "pipeline": sync_remaining_estimate(draft.interview_json),
        }
    draft.status = "interview"
    _add_message(
        db,
        draft=draft,
        role="system",
        content=f"Выбраны процессы: {', '.join(process_ids)}",
        structured={"selectedProcessIds": process_ids, "pipeline": normalize_pipeline(draft.interview_json.get("pipeline"))},
    )
    head = peek_queue_head(draft.interview_json if isinstance(draft.interview_json, dict) else {})
    if head:
        _post_queued_question_message(
            db,
            draft=draft,
            parsed={"status": "need_more"},
            head=head,
        )
    else:
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content="Базовые факты по выбранным процессам уже есть в материалах. Перехожу к уточняющим вопросам.",
            structured={"pipeline": normalize_pipeline(draft.interview_json.get("pipeline"))},
        )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _session(db, draft)


def submit_creation_round_answers(
    db: Session,
    *,
    user_id: str,
    draft_id: str,
    answers: list[dict],
    message: str = "",
) -> RegulationCreationSession:
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    draft.interview_json = apply_round_answers(
        draft.interview_json,
        answers,
        free_message=message,
    )
    draft.draft_document_json = incremental_document_from_state(
        draft.interview_json,
        draft.draft_document_json if isinstance(draft.draft_document_json, dict) else None,
    )
    summary = message.strip() or f"Ответы на раунд: {len(answers)}"
    _add_message(
        db,
        draft=draft,
        role="user",
        content=summary,
        structured={"roundAnswers": answers, "pipeline": normalize_pipeline(draft.interview_json.get("pipeline"))},
    )
    draft.status = "interview"
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return _session(db, draft)


def terminate_active_creation_sessions(db: Session, *, user_id: str) -> dict:
    drafts = (
        db.query(RegulationCreationDraft)
        .filter(
            RegulationCreationDraft.user_id == user_id,
            RegulationCreationDraft.status.in_(list(OPEN_CREATION_STATUSES)),
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
    files: list[tuple[str, bytes]] | None = None,
) -> RegulationCreationSession:
    attachments = _load_creation_attachments(files or [])
    message = request.message.strip()
    if not message and not attachments:
        raise RegulationCreationError("Введите сообщение или приложите файл")
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if draft.status == "finalized":
        return _session(db, draft)
    force_create = _is_force_create_message(message)
    display_message = _display_user_message(message, attachments)
    draft.interview_json = append_user_turn(draft.interview_json, message, attachments)
    _add_message(
        db,
        draft=draft,
        role="user",
        content=display_message,
        structured=_attachments_structured(attachments),
    )
    draft.status = "generating"
    db.add(draft)
    db.commit()

    prompt = build_creation_prompt(
        state=draft.interview_json,
        message=message,
        initial=not draft.cursor_agent_id,
        force_create=force_create,
        include_attachment_bodies=bool(attachments) or not draft.cursor_agent_id,
    )
    try:
        write_document = interview_write_document(draft.interview_json, force_create=force_create)
        if not draft.cursor_agent_id:
            agent_id, run_id = create_agent(prompt, write_document=write_document)
            draft.cursor_agent_id = agent_id
            draft.latest_run_id = run_id
        else:
            run_id = create_run(draft.cursor_agent_id, prompt, write_document=write_document)
            draft.latest_run_id = run_id
        db.add(draft)
        db.commit()
        run = wait_for_run(draft.cursor_agent_id, draft.latest_run_id)
    except CursorAgentError as exc:
        draft.status = "error"
        db.add(draft)
        db.commit()
        raise RegulationCreationError(exc.message, status_code=exc.status_code) from exc

    _apply_agent_reply(
        db,
        user_id=user_id,
        draft=draft,
        raw=str(run.get("result") or ""),
        force_create=force_create,
    )
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
    files: list[tuple[str, bytes]] | None = None,
) -> Iterator[dict]:
    attachments = _load_creation_attachments(files or [])
    message = request.message.strip()
    if not message and not attachments:
        raise RegulationCreationError("Введите сообщение или приложите файл")
    draft = _get_draft(db, user_id=user_id, draft_id=draft_id)
    if draft.status == "finalized":
        yield {"type": "session", "session": _session(db, draft).model_dump(mode="json")}
        return

    force_create = _is_force_create_message(message)
    display_message = _display_user_message(message, attachments)
    draft.interview_json = append_user_turn(draft.interview_json, message, attachments)
    _add_message(
        db,
        draft=draft,
        role="user",
        content=display_message,
        structured=_attachments_structured(attachments),
    )
    draft.status = "generating"
    db.add(draft)
    db.commit()
    yield {"type": "status", "status": "generating"}

    prompt = build_creation_prompt(
        state=draft.interview_json,
        message=message,
        initial=not draft.cursor_agent_id,
        force_create=force_create,
        include_attachment_bodies=bool(attachments) or not draft.cursor_agent_id,
    )
    final_text = ""
    assistant_parts: list[str] = []
    try:
        write_document = interview_write_document(draft.interview_json, force_create=force_create)
        if not draft.cursor_agent_id:
            agent_id, run_id = create_agent(prompt, write_document=write_document)
            draft.cursor_agent_id = agent_id
            draft.latest_run_id = run_id
        else:
            run_id = create_run(draft.cursor_agent_id, prompt, write_document=write_document)
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
                        assistant_parts.append(text)
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
        final_text = "".join(assistant_parts).strip()
    if not final_text:
        try:
            final_text = str(wait_for_run(draft.cursor_agent_id, draft.latest_run_id).get("result") or "")
        except CursorAgentError as exc:
            draft.status = "error"
            db.add(draft)
            db.commit()
            yield {"type": "error", "message": exc.message}
            return

    _apply_agent_reply(db, user_id=user_id, draft=draft, raw=final_text, force_create=force_create)
    db.commit()
    db.refresh(draft)
    yield {"type": "session", "session": _session(db, draft).model_dump(mode="json")}


def _is_early_pipeline_stage(pipeline: dict[str, Any]) -> bool:
    stage = str(pipeline.get("stage") or "")
    phase = str(pipeline.get("interviewPhase") or stage)
    return stage in ("upload", "extract", "select") or phase in ("upload", "extract", "select")


def _processes_for_select_message(state: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    state = ensure_process_selection_state(state)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in state.get("processes") or []:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or item.get("processId") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(
            {
                "id": pid,
                "title": item.get("title"),
                "actor": item.get("actor"),
                "roleStatus": item.get("roleStatus"),
            }
        )
    if out:
        return out
    pipeline = normalize_pipeline(state.get("pipeline"))
    for block in pipeline.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        pid = str(block.get("processId") or block.get("id") or "").strip()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append(
            {
                "id": pid,
                "title": block.get("title") or pid,
                "actor": "",
                "roleStatus": "unclear",
            }
        )
    return out


def _awaiting_process_selection(state: dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        return False
    state = ensure_process_selection_state(state)
    pipeline = normalize_pipeline(state.get("pipeline"))
    stage = str(pipeline.get("stage") or "").lower()
    if stage in ("assemble", "done"):
        return False
    selected = pipeline.get("selectedProcessIds") or []
    if selected:
        return False
    return has_process_candidates(state)


def _post_select_stage_message(
    db: Session,
    *,
    draft: RegulationCreationDraft,
    parsed: dict[str, Any],
) -> None:
    draft.interview_json = replenish_queue(
        normalize_interview_state(draft.interview_json),
        target=FULL_QUEUE_TARGET,
    )
    if isinstance(draft.interview_json, dict):
        draft.interview_json = {
            **draft.interview_json,
            "pipeline": sync_remaining_estimate(draft.interview_json),
        }
    pipeline_now = normalize_pipeline(
        draft.interview_json.get("pipeline") if isinstance(draft.interview_json, dict) else {}
    )
    processes = _processes_for_select_message(
        draft.interview_json if isinstance(draft.interview_json, dict) else {}
    )
    content = (
        "Из документа извлечены процессы. Отметьте нужные — дальше спрошу только то, "
        "чего не удалось однозначно взять из текста документа."
        if processes
        else "Не удалось автоматически выделить процессы из документа. Опишите функции сообщением."
    )
    if _would_duplicate_assistant(db, draft.id, content):
        logger.info("reg_create skip duplicate select prompt draft=%s", draft.id)
        draft.status = "interview"
        if positions := parsed.get("positions"):
            draft.positions_json = [str(item) for item in positions if str(item).strip()]
        return
    _add_message(
        db,
        draft=draft,
        role="assistant",
        content=content,
        structured={
            "quickAnswers": [],
            "pipeline": pipeline_now,
            "processes": processes,
        },
    )
    draft.status = "interview"
    if positions := parsed.get("positions"):
        draft.positions_json = [str(item) for item in positions if str(item).strip()]


def _last_assistant_content(db: Session, draft_id: str) -> str:
    for item in reversed(_messages_for_draft(db, draft_id)):
        if item.role == "assistant":
            return (item.content or "").strip()
        if item.role == "user":
            break
    return ""


def _would_duplicate_assistant(db: Session, draft_id: str, content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return False
    msgs = _messages_for_draft(db, draft_id)
    if not msgs:
        return False
    last = msgs[-1]
    if last.role == "assistant" and (last.content or "").strip() == text:
        return True
    return False


def _chat_awaiting_user_answer(db: Session, draft_id: str) -> bool:
    """True when the last visible chat turn is an unanswered assistant question."""
    msgs = [item for item in _messages_for_draft(db, draft_id) if item.role in {"user", "assistant"}]
    if not msgs:
        return False
    last = msgs[-1]
    if last.role == "user":
        return False
    if last.role != "assistant":
        return False
    structured = last.structured if isinstance(last.structured, dict) else {}
    quick = structured.get("quickAnswers") or structured.get("quick_answers") or []
    return bool(quick)


def _reconcile_stale_queue_head(
    db: Session,
    draft: RegulationCreationDraft,
    interview: dict[str, Any],
) -> dict[str, Any]:
    """Drop queue head that duplicates the last answered assistant question."""
    messages = _messages_for_draft(db, draft.id)
    if not messages or messages[-1].role != "user":
        return interview
    last_assistant = next((item for item in reversed(messages) if item.role == "assistant"), None)
    if not last_assistant:
        return interview
    head = peek_queue_head(interview)
    if not head:
        return interview
    head_text = str(head.get("text") or "").strip()
    if head_text and (last_assistant.content or "").strip() == head_text:
        interview = consume_queue_head(interview, question_id=str(head.get("id") or ""))
        draft.interview_json = interview
    return interview


def _strip_duplicate_prefetch_turn(
    db: Session,
    draft: RegulationCreationDraft,
    turn: RegulationCreationTurn,
) -> RegulationCreationTurn:
    raw = (turn.prefetchedReply or "").strip()
    if not raw:
        return turn
    try:
        parsed = _parse_agent_response(raw)
    except Exception:
        return turn
    message = str(parsed.get("message") or "").strip()
    if message and _would_duplicate_assistant(db, draft.id, message):
        logger.info("reg_create strip duplicate prefetch draft=%s", draft.id)
        return turn.model_copy(update={"prefetchedReply": ""})
    return turn


def _post_queued_question_message(
    db: Session,
    *,
    draft: RegulationCreationDraft,
    parsed: dict[str, Any],
    head: dict[str, Any],
    force_post: bool = False,
) -> None:
    quick_answers = head.get("options") or []
    raw_content = str(head.get("text") or "").strip()
    if not raw_content:
        return
    if not force_post and _would_duplicate_assistant(db, draft.id, raw_content):
        logger.info("reg_create skip duplicate queued question draft=%s q=%s", draft.id, head.get("id"))
        draft.status = "interview"
        if positions := parsed.get("positions"):
            draft.positions_json = [str(item) for item in positions if str(item).strip()]
        return
    draft.interview_json, content = remember_assistant_question(
        draft.interview_json,
        message=raw_content,
        quick_answers=quick_answers,
        function_id=str(head.get("processId") or "").strip(),
        field=str(head.get("field") or "").strip(),
        process_id=str(head.get("processId") or "").strip(),
        queue_question_id=str(head.get("id") or "").strip(),
    )
    draft.interview_json = consume_queue_head(
        draft.interview_json,
        question_id=str(head.get("id") or "").strip(),
    )
    pipeline_now = normalize_pipeline(
        draft.interview_json.get("pipeline") if isinstance(draft.interview_json, dict) else {}
    )
    _add_message(
        db,
        draft=draft,
        role="assistant",
        content=content,
        structured={
            "quickAnswers": quick_answers,
            "roundQuestions": [dict(head)],
            "pipeline": pipeline_now,
            "processes": _processes_for_select_message(
                draft.interview_json if isinstance(draft.interview_json, dict) else {}
            ),
        },
    )
    draft.status = "interview"
    if positions := parsed.get("positions"):
        draft.positions_json = [str(item) for item in positions if str(item).strip()]


def _apply_research_reply(
    db: Session,
    *,
    draft: RegulationCreationDraft,
    raw: str,
    research_agent_id: str = "",
) -> None:
    raw = raw.strip()
    if not raw:
        return
    if research_agent_id.strip():
        draft.interview_json = set_research_sdk_agent_id(draft.interview_json, research_agent_id)
    parsed = _parse_agent_response(raw)
    state = draft.interview_json if isinstance(draft.interview_json, dict) else {}
    if isinstance(parsed.get("materialReview"), list):
        state = apply_material_review(state, parsed)
        pipe = normalize_pipeline(state.get("pipeline"))
        pipe["materialReviewDone"] = True
        pipe["materialReviewPending"] = False
        state["pipeline"] = pipe
    state = apply_research_payload(state, parsed)
    pipeline = normalize_pipeline(state.get("pipeline"))
    state["researchPrefetchAt"] = int(time.time())
    state["researchPrefetchAtAsked"] = int(pipeline.get("questionsAskedTotal") or 0)
    state.pop("_regulationGapReportCache", None)
    draft.interview_json = state
    logger.info(
        "[research-agent] facts=%s draft=%s",
        len(parsed.get("researchFacts") or []) if isinstance(parsed.get("researchFacts"), list) else 0,
        draft.id,
    )


def _maybe_spawn_process_agents(
    db: Session,
    *,
    user_id: str,
    draft: RegulationCreationDraft,
) -> list[dict[str, Any]]:
    if not dual_workflow_enabled(draft.interview_json if isinstance(draft.interview_json, dict) else {}):
        return []
    interview = draft.interview_json if isinstance(draft.interview_json, dict) else {}
    title = ""
    if isinstance(draft.draft_document_json, dict):
        title = str(draft.draft_document_json.get("title") or "")
    created_entries, updated_interview = spawn_regulation_process_agents(
        db,
        user_id=user_id,
        interview=interview,
        regulation_title=title,
    )
    if not created_entries:
        return []
    draft.interview_json = updated_interview
    names = ", ".join(f"«{item.get('title')}»" for item in created_entries if isinstance(item, dict))
    _add_message(
        db,
        draft=draft,
        role="system",
        content=f"Созданы агенты в «Мои агенты»: {names}.",
        structured={"spawnedAgents": created_entries},
    )
    return created_entries


def _apply_prefetch_reply(
    db: Session,
    *,
    draft: RegulationCreationDraft,
    raw: str,
) -> None:
    raw = raw.strip()
    if not raw:
        return
    parsed = _parse_agent_response(raw)
    round_questions = parsed.get("roundQuestions")
    if not isinstance(round_questions, list):
        interview = parsed.get("interview") if isinstance(parsed.get("interview"), dict) else {}
        round_questions = interview.get("roundQuestions") if isinstance(interview, dict) else None
    if not isinstance(round_questions, list) or not round_questions:
        return
    pipeline = normalize_pipeline(
        draft.interview_json.get("pipeline") if isinstance(draft.interview_json, dict) else {}
    )
    selected = {str(item).strip() for item in (pipeline.get("selectedProcessIds") or []) if str(item).strip()}
    filtered = _drop_known_questions(
        draft.interview_json if isinstance(draft.interview_json, dict) else {},
        _filter_round_questions(round_questions, selected),
    )
    if filtered:
        draft.interview_json = enqueue_round_batch(draft.interview_json, filtered)
    logger.info(
        "[prefetch-queue] enqueued=%s draft=%s depth=%s",
        len(filtered or []),
        draft.id,
        queue_depth(draft.interview_json if isinstance(draft.interview_json, dict) else {}),
    )
    if filtered:
        _ensure_queued_question_posted(db, draft)


def _ensure_queued_question_posted(db: Session, draft: RegulationCreationDraft) -> None:
    """Post the next queued interview question when chat is idle."""
    if _chat_awaiting_user_answer(db, draft.id):
        return
    interview = normalize_interview_state(
        draft.interview_json if isinstance(draft.interview_json, dict) else {}
    )
    interview = resume_interview_if_pending(interview)
    draft.interview_json = interview
    pipeline = normalize_pipeline(interview.get("pipeline"))
    if not pending_interview_work(interview):
        return
    if not (pipeline.get("selectedProcessIds") or []):
        return
    if _has_open_current_question(interview):
        current = interview.get("currentQuestion") if isinstance(interview.get("currentQuestion"), dict) else {}
        if not _clean_str(current.get("answer")):
            interview.pop("currentQuestion", None)
            draft.interview_json = interview
        if _has_open_current_question(interview):
            return
    if queue_depth(interview) <= 0:
        interview = replenish_queue(interview, target=FULL_QUEUE_TARGET)
        draft.interview_json = interview
    interview = _reconcile_stale_queue_head(db, draft, interview)
    head = peek_queue_head(interview)
    if not head:
        return
    text = str(head.get("text") or "").strip()
    if text and _would_duplicate_assistant(db, draft.id, text):
        return
    _post_queued_question_message(
        db,
        draft=draft,
        parsed={"status": "need_more"},
        head=head,
        force_post=True,
    )


def _autostart_assemble_when_ready(db: Session, draft: RegulationCreationDraft) -> bool:
    """Switch to assemble automatically once interview gaps are fully closed."""
    interview = normalize_interview_state(
        draft.interview_json if isinstance(draft.interview_json, dict) else {}
    )
    interview = resume_interview_if_pending(interview)
    if pending_interview_work(interview):
        draft.interview_json = interview
        return False
    pipeline = normalize_pipeline(interview.get("pipeline"))
    if str(pipeline.get("stage") or "") != "interview":
        draft.interview_json = interview
        return False
    if not (pipeline.get("selectedProcessIds") or []):
        draft.interview_json = interview
        return False
    if processes_need_collect_questions(interview) and int(pipeline.get("questionsAskedTotal") or 0) <= 0:
        interview = replenish_queue(interview, target=FULL_QUEUE_TARGET)
        head = peek_queue_head(interview)
        if head:
            draft.interview_json = interview
            _post_queued_question_message(
                db,
                draft=draft,
                parsed={"status": "need_more"},
                head=head,
                force_post=True,
            )
            db.add(draft)
            db.commit()
            return False
        draft.interview_json = interview
        return False
    if interview.get("document_write_required"):
        draft.interview_json = interview
        return False
    interview = {**interview, "document_write_required": True}
    interview = set_pipeline_stage(interview, "assemble")
    interview.pop("currentQuestion", None)
    pipe = normalize_pipeline(interview.get("pipeline"))
    pipe["roundQuestions"] = []
    interview["pipeline"] = sync_remaining_estimate({**interview, "pipeline": pipe})
    draft.interview_json = interview
    draft.status = "interview"
    assemble_msg = "Факты по выбранным процессам собраны. Формирую регламент."
    if not _would_duplicate_assistant(db, draft.id, assemble_msg):
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content=assemble_msg,
            structured={
                "pipeline": normalize_pipeline(interview.get("pipeline")),
                "documentWritePending": True,
            },
        )
    return True


def _apply_agent_reply(
    db: Session,
    *,
    user_id: str,
    draft: RegulationCreationDraft,
    raw: str,
    force_create: bool = False,
) -> None:
    raw = raw.strip()
    parsed = _parse_agent_response(raw)
    if str(parsed.get("status") or "").strip().lower() in {"question", "in_progress"}:
        parsed["status"] = "need_more"
    if is_replacement_garbage(parsed.get("message")) or is_replacement_garbage(raw):
        parsed["message"] = (
            "Ответ агента пришёл в нечитаемом виде. Нажмите отправку ещё раз "
            "или коротко напишите должность и первую функцию."
        )
        parsed["quickAnswers"] = [
            "Повторить разбор файлов",
            "Опишу функции сообщением",
        ]
        parsed["status"] = "need_more"
    merge_started = perf_counter()
    draft.interview_json = merge_agent_payload(draft.interview_json, parsed)
    chosen_ids = selected_process_ids(draft.interview_json)
    if chosen_ids and (
        is_process_select_message(parsed.get("message"))
        or is_process_select_message(_message_content(parsed, raw))
        or str((parsed.get("pipeline") or {}).get("stage") or "").lower() == "select"
    ):
        _force_gap_question(parsed, draft)
    if chosen_ids and str(parsed.get("status") or "") == "need_more":
        current_id = current_interview_process_id(draft.interview_json)
        next_question = parsed.get("nextQuestion") if isinstance(parsed.get("nextQuestion"), dict) else {}
        process_blob = parsed.get("process") if isinstance(parsed.get("process"), dict) else {}
        asked_process = normalize_process_id(
            next_question.get("processId")
            or next_question.get("functionId")
            or process_blob.get("id")
        )
        if current_id and asked_process and asked_process != current_id:
            _force_gap_question(parsed, draft)
        elif _should_replace_with_gap_question(_message_content(parsed, raw)):
            _force_gap_question(parsed, draft)
    blocker = None if force_create or parsed.get("status") != "ready" else ready_blocker(parsed, draft.interview_json)
    if blocker is not None:
        draft.interview_json, message = remember_assistant_question(
            draft.interview_json,
            message=blocker.message,
            quick_answers=blocker.quick_answers,
            function_id=blocker.function_id,
            field=blocker.field,
        )
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content=message,
            structured={
                "quickAnswers": blocker.quick_answers,
                "blockedReady": {
                    "functionId": blocker.function_id,
                    "field": blocker.field,
                },
                "pipeline": normalize_pipeline(
                    draft.interview_json.get("pipeline") if isinstance(draft.interview_json, dict) else {}
                ),
                "roundQuestions": normalize_pipeline(
                    draft.interview_json.get("pipeline") if isinstance(draft.interview_json, dict) else {}
                ).get("roundQuestions")
                or [],
            },
        )
        draft.status = "interview"
        if positions := parsed.get("positions"):
            draft.positions_json = [str(item) for item in positions if str(item).strip()]
        db.add(draft)
        return
    document = parsed.get("document") if isinstance(parsed.get("document"), dict) else None
    wants_document = parsed.get("status") == "ready" or force_create
    has_full_document = document_has_full_text(document)
    if wants_document and not has_full_document and not force_create:
        state = draft.interview_json if isinstance(draft.interview_json, dict) else {}
        if pending_interview_work(state):
            draft.interview_json = resume_interview_if_pending(state)
            _ensure_queued_question_posted(db, draft)
            draft.status = "interview"
            db.add(draft)
            return
        draft.interview_json = {**state, "document_write_required": True}
        draft.interview_json = set_pipeline_stage(draft.interview_json, "assemble")
        draft.interview_json.pop("currentQuestion", None)
        pipeline = normalize_pipeline(draft.interview_json.get("pipeline"))
        pipeline["roundQuestions"] = []
        draft.interview_json["pipeline"] = sync_remaining_estimate({**draft.interview_json, "pipeline": pipeline})
        draft.status = "interview"
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content=(
                parsed.get("message")
                or "Интервью завершено. Формирую текст регламента по собранным данным — подождите."
            ),
            structured={
                "pipeline": normalize_pipeline(draft.interview_json.get("pipeline")),
                "documentWritePending": True,
            },
        )
        if positions := parsed.get("positions"):
            draft.positions_json = [str(item) for item in positions if str(item).strip()]
        db.add(draft)
        return
    if wants_document and force_create and not document_has_body(document):
        title = str((document or {}).get("title") or "").strip()
        document = document_from_interview(draft.interview_json, title)
    if wants_document and force_create and not document_has_body(document):
        document = _stub_document(parsed, title=str((document or {}).get("title") or "").strip())
    if wants_document and not document_has_full_text(document) and processes_need_collect_questions(
        draft.interview_json if isinstance(draft.interview_json, dict) else {}
    ):
        draft.interview_json = resume_interview_if_pending(
            draft.interview_json if isinstance(draft.interview_json, dict) else {}
        )
        draft.interview_json = replenish_queue(
            normalize_interview_state(draft.interview_json),
            target=FULL_QUEUE_TARGET,
        )
        _ensure_queued_question_posted(db, draft)
        draft.status = "interview"
        db.add(draft)
        return
    if wants_document and (has_full_document or (force_create and document_has_full_text(document))):
        if isinstance(draft.interview_json, dict):
            draft.interview_json.pop("document_write_required", None)
        draft.interview_json = set_pipeline_stage(draft.interview_json, "assemble")
        try:
            _maybe_spawn_process_agents(db, user_id=user_id, draft=draft)
            result = _finalize_document(db, user_id=user_id, draft=draft, document=document or {})
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
        draft.interview_json = set_pipeline_stage(draft.interview_json, "done")
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content=parsed.get("message") or "Регламент сформирован. Проверьте документ перед созданием агента.",
            structured={"resultRegulationId": result.regulationId, "document": document, "pipeline": normalize_pipeline(draft.interview_json.get("pipeline"))},
        )
        draft.status = "finalized"
        draft.result_regulation_id = result.regulationId
        spawned = (draft.interview_json or {}).get("spawnedAgents") if isinstance(draft.interview_json, dict) else []
        if isinstance(spawned, list) and spawned:
            names = ", ".join(f"«{x.get('title')}»" for x in spawned if isinstance(x, dict) and x.get("title"))
            if names:
                _add_message(
                    db,
                    draft=draft,
                    role="assistant",
                    content=f"Регламент готов. Новые агенты в «Мои агенты»: {names}.",
                    structured={"spawnedAgents": spawned, "resultRegulationId": result.regulationId},
                )
    elif early_stage and not force_create:
        _post_select_stage_message(db, draft=draft, parsed=parsed)
    elif (
        _awaiting_process_selection(
            draft.interview_json if isinstance(draft.interview_json, dict) else {}
        )
        and not force_create
    ):
        _post_select_stage_message(db, draft=draft, parsed=parsed)
    elif (
        pipeline.get("stage") == "interview"
        and queue_has_items
        and (pipeline.get("selectedProcessIds") or [])
        and not force_create
        and not round_questions
    ):
        interview_state = draft.interview_json if isinstance(draft.interview_json, dict) else {}
        head = peek_queue_head(interview_state)
        if head:
            logger.info("[deterministic-queue] serving head=%s draft=%s", head.get("id"), draft.id)
            _post_queued_question_message(db, draft=draft, parsed=parsed, head=head)
        else:
            db.add(draft)
    else:
        if (
            _awaiting_process_selection(
                draft.interview_json if isinstance(draft.interview_json, dict) else {}
            )
            and not force_create
        ):
            _post_select_stage_message(db, draft=draft, parsed=parsed)
            draft.status = "interview"
            if positions := parsed.get("positions"):
                draft.positions_json = [str(item) for item in positions if str(item).strip()]
            db.add(draft)
            return
        quick_answers = _quick_answers(parsed.get("quickAnswers"))
        content = _message_content(parsed, raw)
        draft.interview_json, content = remember_assistant_question(
            draft.interview_json,
            message=content,
            quick_answers=quick_answers,
            function_id=_message_function_id(parsed, draft.interview_json),
            field=_message_field(parsed, draft.interview_json),
            already_known=_message_already_known(parsed),
            missing_fact=_message_missing_fact(parsed),
            why_this_question=_message_why(parsed),
        )
        _add_message(
            db,
            draft=draft,
            role="assistant",
            content=content,
            structured=_assistant_question_structured(parsed, draft.interview_json, quick_answers),
        )
        rq = pipeline_now.get("roundQuestions") or []
        queued_meta = queued_question_metadata(parsed)
        head = peek_queue_head(draft.interview_json if isinstance(draft.interview_json, dict) else {})
        if rq and head:
            content = str(head.get("text") or "").strip() or content
            quick_answers = head.get("options") or quick_answers
            draft.interview_json, content = remember_assistant_question(
                draft.interview_json,
                message=content,
                quick_answers=quick_answers,
                function_id=str(head.get("processId") or "").strip(),
                field=str(head.get("field") or "").strip(),
                process_id=str(head.get("processId") or "").strip(),
                queue_question_id=str(head.get("id") or queued_meta.get("id") or "").strip(),
            )
            draft.interview_json = consume_queue_head(
                draft.interview_json,
                question_id=str(head.get("id") or "").strip(),
            )
            rq = [dict(head)] if head else rq[:1]
        elif rq:
            draft.interview_json = draft.interview_json if isinstance(draft.interview_json, dict) else {}
        else:
            function_id = queued_meta.get("processId") or _message_function_id(parsed, draft.interview_json)
            field = queued_meta.get("field") or _message_field(parsed, draft.interview_json)
            if not field:
                field = _infer_field_from_assistant_content(content)
            draft.interview_json, content = remember_assistant_question(
                draft.interview_json,
                message=content,
                quick_answers=quick_answers,
                function_id=function_id,
                field=field,
                process_id=queued_meta.get("processId") or function_id,
                queue_question_id=str(queued_meta.get("id") or (head or {}).get("id") or "").strip(),
            )
            if queued_meta.get("id"):
                draft.interview_json = consume_queue_head(
                    draft.interview_json,
                    question_id=queued_meta.get("id"),
                )
            else:
                draft.interview_json = consume_queue_head(draft.interview_json)
        processes = []
        if isinstance(draft.interview_json, dict):
            processes = [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "actor": item.get("actor"),
                    "roleStatus": item.get("roleStatus"),
                }
                for item in (draft.interview_json.get("processes") or [])
                if isinstance(item, dict)
            ]
        if not _would_duplicate_assistant(db, draft.id, content):
            _add_message(
                db,
                draft=draft,
                role="assistant",
                content=content,
                structured={
                    "quickAnswers": quick_answers,
                    "roundQuestions": rq,
                    "pipeline": pipeline_now,
                    "processes": processes,
                },
            )
        else:
            logger.info("reg_create skip duplicate assistant reply draft=%s", draft.id)
        draft.status = "interview"
        if positions := parsed.get("positions"):
            draft.positions_json = [str(item) for item in positions if str(item).strip()]


def _build_fastpath_reply(
    *,
    interview: dict[str, Any],
    pipeline: dict[str, Any],
    force_create: bool,
) -> str:
    return build_fastpath_reply_from_queue(
        interview=interview,
        pipeline=pipeline,
        force_create=force_create,
    )


def _finalize_document(
    db: Session,
    *,
    user_id: str,
    draft: RegulationCreationDraft,
    document: dict,
) -> RegulationParseResult:
    document = _attach_creation_quality(document)
    output_dir = settings.regulation_storage_dir / "created" / draft.id
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / _safe_filename(str(document.get("title") or "created-regulation"))
    path = path.with_suffix(".docx")
    _write_docx(path, document)
    regulation_id = new_regulation_id()
    stored = save_upload(regulation_id=regulation_id, filename=path.name, data=path.read_bytes())
    result = _result_from_created_document(
        regulation_id=regulation_id,
        filename=path.name,
        document=document,
    )
    db.add(
        RegulationDocument(
            id=regulation_id,
            user_id=user_id,
            file_name=path.name,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            storage_path=str(stored),
            is_scan=False,
            result_json=result.model_dump(mode="json"),
        )
    )
    draft.result_document_path = str(path)
    draft.draft_document_json = document
    return result


def _result_from_created_document(
    *,
    regulation_id: str,
    filename: str,
    document: dict,
) -> RegulationParseResult:
    title = str(document.get("title") or "Регламент").strip() or "Регламент"
    fragments: list[RegulationFragment] = []
    sections: list[str] = []
    index = 0
    for section, section_title, section_path, _level in _iter_document_sections(
        document.get("sections") or [],
        parent_path=[title],
    ):
        section_title = section_title or f"Раздел {index + 1}"
        if section_title not in sections:
            sections.append(section_title)
        texts = [section_title] if section_title else []
        for paragraph in section.get("paragraphs") or []:
            value = str(paragraph or "").strip()
            if value:
                texts.append(value)
        for item in section.get("items") or []:
            value = _document_item_text(item)
            if value:
                texts.append(value)
        for text in texts:
            index += 1
            fragments.append(
                RegulationFragment(
                    fragmentId=f"{regulation_id}-block-{index:02d}",
                    page=1,
                    section=section_title,
                    sectionPath=section_path or [title, section_title],
                    kind="text",
                    blockType="heading" if text == section_title else "paragraph",
                    text=text,
                    isBold=text == section_title,
                )
            )
    if not fragments:
        fragments.append(
            RegulationFragment(
                fragmentId=f"{regulation_id}-block-01",
                page=1,
                section=title,
                sectionPath=[title],
                kind="text",
                blockType="heading",
                text=title,
                isBold=True,
            )
        )
        sections = [title]
    return RegulationParseResult(
        regulationId=regulation_id,
        fileName=filename,
        pageCount=1,
        sectionCount=len(sections),
        recognitionQuality=1.0,
        isScan=False,
        sections=sections,
        fragments=fragments,
    )


def _stub_document(parsed: dict, *, title: str) -> dict:
    message = str(parsed.get("message") or "").strip() or "Регламент сформирован по текущим данным."
    return {
        "title": title or "Регламент",
        "sections": [
            {
                "number": "1",
                "title": "Порядок",
                "paragraphs": [message],
                "items": [],
            }
        ],
    }


def _write_docx(path: Path, document: dict) -> None:
    if STO_TEMPLATE_PATH.is_file():
        try:
            fill_sto_regulation(document, path)
            return
        except Exception:
            logger.exception("reg_create sto-template fill failed, fallback to markdown writer")
    markdown_text = _document_to_markdown(document)
    try:
        markdown_to_docx(markdown_text, path)
        return
    except ImportError as exc:
        raise RegulationCreationError("Для создания DOCX требуется python-docx", status_code=500) from exc
    except RuntimeError as exc:
        raise RegulationCreationError(str(exc), status_code=500) from exc
    except Exception:
        logger.exception("reg_create markdown->docx failed, fallback to legacy writer")
    _write_docx_legacy(path, document)


def _write_docx_legacy(path: Path, document: dict) -> None:
    try:
        from docx import Document
    except ImportError as exc:
        raise RegulationCreationError("Для создания DOCX требуется python-docx", status_code=500) from exc
    doc = Document()
    title = str(document.get("title") or "Регламент")
    doc.add_heading(title, level=1)
    for section, heading, _section_path, level in _iter_document_sections(
        document.get("sections") or [],
        parent_path=[title],
    ):
        if heading:
            doc.add_heading(heading, level=min(max(level, 2), 9))
        for paragraph in section.get("paragraphs") or []:
            text = str(paragraph or "").strip()
            if text:
                doc.add_paragraph(text)
        for item in section.get("items") or []:
            _add_docx_item(doc, item, level=0)
    doc.save(str(path))


def _load_creation_template_structure() -> dict[str, Any]:
    global _creation_template_structure_cache
    cached = _creation_template_structure_cache
    if cached is not None:
        return cached
    if not _REGULATION_TEMPLATE_STRUCTURE_PATH.is_file():
        _creation_template_structure_cache = {}
        return {}
    try:
        _creation_template_structure_cache = load_structure_json(_REGULATION_TEMPLATE_STRUCTURE_PATH)
    except Exception:
        logger.exception(
            "reg_create failed to read structure template path=%s",
            ascii(str(_REGULATION_TEMPLATE_STRUCTURE_PATH)),
        )
        _creation_template_structure_cache = {}
    return _creation_template_structure_cache or {}


def _attach_creation_quality(document: dict) -> dict:
    clean = dict(document or {})
    clean.pop("_quality", None)
    markdown_text = _document_to_markdown(clean)
    soft_report = validate_regulation_markdown(markdown_text, structure={})
    structure = _load_creation_template_structure()
    template_report = (
        validate_regulation_markdown(markdown_text, structure=structure)
        if structure
        else {"ok": True, "stats": {"errors": 0, "warnings": 0, "completeness_score": 100}, "issues": []}
    )
    quality = {
        "rulesVersion": _REGULATION_RULES_VERSION,
        "softReport": soft_report,
        "templateReport": template_report,
        "templateUsed": bool(structure),
    }
    return {**clean, "_quality": quality}


def _document_to_markdown(document: dict) -> str:
    title = str(document.get("title") or "Регламент").strip() or "Регламент"
    lines = [f"# {title}", ""]
    for section, heading, _section_path, level in _iter_document_sections(
        document.get("sections") or [],
        parent_path=[title],
    ):
        if heading:
            marks = "#" * min(max(level, 2), 6)
            lines.append(f"{marks} {heading}")
        for paragraph in section.get("paragraphs") or []:
            text = str(paragraph or "").strip()
            if text:
                lines.append(text)
        for item in section.get("items") or []:
            _append_markdown_item(lines, item, level=0)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _append_markdown_item(lines: list[str], item: object, *, level: int) -> None:
    text = _document_item_text(item)
    if text:
        lines.append(f"{'  ' * level}- {text}")
    if isinstance(item, dict):
        children = item.get("items") or item.get("children") or []
        if isinstance(children, list):
            for child in children:
                _append_markdown_item(lines, child, level=level + 1)


def _iter_document_sections(
    sections: object,
    *,
    parent_path: list[str],
    level: int = 2,
) -> Iterator[tuple[dict, str, list[str], int]]:
    if not isinstance(sections, list):
        return
    for section in sections:
        if not isinstance(section, dict):
            continue
        heading = _document_section_heading(section)
        section_path = [*parent_path, heading] if heading else parent_path
        yield section, heading, section_path, level
        for key in ("sections", "subsections", "children"):
            yield from _iter_document_sections(
                section.get(key),
                parent_path=section_path,
                level=level + 1,
            )


def _document_section_heading(section: dict) -> str:
    heading = str(section.get("title") or "").strip()
    number = str(section.get("number") or "").strip()
    return f"{number} {heading}".strip() if heading else ""


def _document_item_text(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("text") or item.get("title") or "").strip()
    return str(item or "").strip()


def _add_docx_item(doc: object, item: object, *, level: int) -> None:
    text = _document_item_text(item)
    if text:
        style = "List Bullet" if level <= 0 else "List Bullet 2"
        doc.add_paragraph(text, style=style)
    if isinstance(item, dict):
        children = item.get("items") or item.get("children") or []
        if isinstance(children, list):
            for child in children:
                _add_docx_item(doc, child, level=level + 1)


def _load_creation_attachments(files: list[tuple[str, bytes]]) -> list[dict]:
    loaded: list[dict] = []
    total_chars = 0
    for name, raw in files:
        suffix = Path(name or "").suffix.lower()
        safe_name = ascii(Path(name or "file").name)
        logger.info(
            "reg_create attachment load start name=%s suffix=%s bytes=%s",
            safe_name,
            suffix,
            len(raw),
        )
        if suffix == ".doc":
            raise RegulationCreationError("Формат DOC не поддерживается. Сохраните файл как DOCX.")
        if suffix not in _CREATION_ATTACH_SUFFIXES:
            raise RegulationCreationError(
                f"Формат «{suffix or 'без расширения'}» не поддерживается. "
                "Допустимо: docx, pdf, md, txt."
            )
        try:
            item = _load_creation_attachment(name, raw)
        except DocumentError as exc:
            file_name = Path(name).name or "file"
            logger.warning(
                "reg_create attachment load failed name=%s suffix=%s detail=%s; keep stub",
                safe_name,
                suffix,
                ascii(str(exc)),
            )
            loaded.append(
                {
                    "name": file_name,
                    "text": f"Файл {file_name} не удалось прочитать: {exc}",
                    "kind": "text",
                    "mime_type": "application/octet-stream",
                    "data_b64": "",
                    "read_error": str(exc),
                }
            )
            continue
        text = str(item.get("text") or "")
        logger.info(
            "reg_create attachment load ok name=%s kind=%s chars=%s",
            safe_name,
            ascii(str(item.get("kind") or "")),
            len(text),
        )
        remain = max(0, _MAX_ATTACH_CHARS - total_chars)
        if len(text) > remain:
            item["text"] = text[:remain] + "\n...[текст файла обрезан]"
            text = str(item["text"])
        total_chars += len(text)
        loaded.append(item)
        if total_chars >= _MAX_ATTACH_CHARS:
            break
    return loaded


def _load_creation_attachment(name: str, raw: bytes) -> dict:
    suffix = Path(name or "").suffix.lower()
    if suffix != ".pdf":
        return load_attachment_bytes(name, raw)
    safe_name = ascii(Path(name or "scan.pdf").name)
    logger.info("reg_create pdf text extraction start name=%s bytes=%s", safe_name, len(raw))
    try:
        item = load_attachment_bytes(name, raw)
        logger.info(
            "reg_create pdf text extraction ok name=%s chars=%s",
            safe_name,
            len(str(item.get("text") or "")),
        )
        return item
    except DocumentError as exc:
        if "Документ пуст" not in str(exc):
            logger.warning(
                "reg_create pdf text extraction failed name=%s detail=%s",
                safe_name,
                ascii(str(exc)),
            )
            raise
        logger.info(
            "reg_create pdf text empty; ocr fallback start name=%s detail=%s",
            safe_name,
            ascii(str(exc)),
        )
    with tempfile.TemporaryDirectory(prefix="reg-create-ocr-") as tmp:
        path = Path(tmp) / (Path(name).name or "scan.pdf")
        path.write_bytes(raw)
        try:
            is_scan, _page_count = is_scan_pdf(path)
        except RuntimeError as exc:
            logger.warning(
                "reg_create pdf scan detection failed name=%s detail=%s",
                safe_name,
                ascii(str(exc)),
            )
            raise DocumentError(str(exc)) from exc
        logger.info(
            "reg_create pdf scan detection ok name=%s is_scan=%s pages=%s",
            safe_name,
            is_scan,
            _page_count,
        )
        if not is_scan:
            logger.warning("reg_create pdf has no text and is not scan name=%s", safe_name)
            raise DocumentError("Документ пуст или не удалось извлечь текст.")
        try:
            logger.info("reg_create pdf ocr start name=%s pages=%s", safe_name, _page_count)
            extracted = extract_pdf_scan(path, work_dir=Path(tmp))
        except RuntimeError as exc:
            logger.warning(
                "reg_create pdf ocr failed name=%s detail=%s",
                safe_name,
                ascii(str(exc)),
            )
            raise DocumentError(str(exc)) from exc
        logger.info(
            "reg_create pdf ocr ok name=%s pages=%s blocks=%s",
            safe_name,
            extracted.page_count,
            len(extracted.blocks),
        )
    text = compose_regulation_text(
        RegulationParseResult(
            regulationId="reg-create-attachment",
            fileName=Path(name).name or "scan.pdf",
            pageCount=extracted.page_count,
            isScan=extracted.is_scan,
            fragments=[
                {
                    "fragmentId": block.block_id or f"ocr-{index}",
                    "page": block.page,
                    "section": block.section or "",
                    "kind": block.kind,
                    "blockType": block.block_type,
                    "text": block.text,
                    "ocrConfidence": block.confidence,
                }
                for index, block in enumerate(extracted.blocks, start=1)
                if (block.text or "").strip()
            ],
        )
    )
    if not text.strip():
        logger.warning("reg_create pdf ocr produced empty text name=%s", safe_name)
        raise DocumentError("Документ пуст или не удалось извлечь текст.")
    logger.info("reg_create pdf ocr text composed name=%s chars=%s", safe_name, len(text))
    return {
        "name": Path(name).name or "scan.pdf",
        "text": text,
        "kind": "text",
        "mime_type": "application/pdf",
        "data_b64": "",
    }


def _display_user_message(message: str, attachments: list[dict]) -> str:
    # Files are rendered from structured.attachments, not from message text.
    _ = attachments
    return (message or "").strip()


def _attachments_structured(attachments: list[dict]) -> dict:
    if not attachments:
        return {}
    return {
        "attachments": [
            {
                "name": str(item.get("name") or "file"),
                "shortName": _short_attachment_name(str(item.get("name") or "file")),
            }
            for item in attachments
        ]
    }


def _short_attachment_name(name: str, keep: int = 6) -> str:
    path = Path(name)
    stem = path.stem.replace(" ", "_")
    suffix = path.suffix.lower()
    if len(stem) <= keep:
        return f"{stem}{suffix}"
    return f"{stem[:keep]}...{suffix}"


def _first_interview_object(raw: str) -> dict | None:
    decoder = json.JSONDecoder()
    text = raw or ""
    index = 0
    while index < len(text):
        start = text.find("{", index)
        if start < 0:
            break
        try:
            obj, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        status = str(obj.get("status") or "").strip().lower() if isinstance(obj, dict) else ""
        if isinstance(obj, dict) and status in {"need_more", "ready", "question", "in_progress"}:
            if status in {"question", "in_progress"}:
                obj["status"] = "need_more"
            return obj
        index = end
    return None


def _parse_agent_response(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    first = _first_interview_object(text)
    if first is not None:
        if not str(first.get("message") or "").strip():
            prose = leading_question_text(text)
            if prose:
                first["message"] = prose
        return first
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


def _assistant_question_structured(parsed: dict, interview: object, quick_answers: list[str]) -> dict:
    structured: dict = {"quickAnswers": list(quick_answers)}
    pipeline = parsed.get("pipeline") if isinstance(parsed.get("pipeline"), dict) else {}
    chosen_ids = selected_process_ids(interview)
    if chosen_ids:
        stage = str(pipeline.get("stage") or "").strip() or "questions"
        if stage.lower() == "select":
            stage = "questions"
        pipeline = {
            **pipeline,
            "stage": stage,
            "selectedProcessIds": chosen_ids,
        }
    if pipeline:
        structured["pipeline"] = pipeline
    processes = _ui_processes(parsed, interview)
    if processes:
        structured["processes"] = processes
    return structured


def _ui_processes(parsed: dict, interview: object) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(raw: object) -> None:
        if not isinstance(raw, dict):
            return
        process_id = normalize_process_id(raw.get("processId") or raw.get("id"))
        title = str(raw.get("title") or raw.get("name") or process_id).strip()
        if not process_id or process_id in seen:
            return
        seen.add(process_id)
        items.append(
            {
                "id": process_id,
                "title": title,
                "actor": str(raw.get("actor") or "").strip(),
                "roleStatus": str(raw.get("roleStatus") or "").strip(),
            }
        )

    interview_payload = parsed.get("interview") if isinstance(parsed.get("interview"), dict) else {}
    for source in (
        parsed.get("processes"),
        interview_payload.get("processes"),
        (parsed.get("pipeline") or {}).get("blocks") if isinstance(parsed.get("pipeline"), dict) else None,
        interview.get("processes") if isinstance(interview, dict) else None,
    ):
        if isinstance(source, list):
            for raw in source:
                add(raw)
    return items


def _quick_answers(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    answers = [str(item).strip() for item in value if str(item).strip()]
    answers = [
        item
        for item in answers
        if item.lower() not in {"оставить", "переделать", "оставить это"}
    ]
    return answers[:6]


def _should_replace_with_gap_question(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return True
    folded = text.lower()
    if "?" in text or "？" in text:
        # Still replace pure gap statements that only tack on a weak question mark.
        gap_only = (
            "не раскрыт",
            "не указан",
            "не указано",
            "не хватает",
            "отсутствует",
            "неясн",
            "упомянут",
            "в тексте нет",
        )
        ask_markers = (
            "как ",
            "какой",
            "какая",
            "какие",
            "где ",
            "когда ",
            "уточните",
            "опишите",
            "расскажите",
            "относится",
        )
        if any(marker in folded for marker in gap_only) and not any(
            marker in folded for marker in ask_markers
        ):
            return True
        return False
    status_markers = (
        "нет пробел",
        "пробелов нет",
        "больше нет",
        "все известно",
        "всё известно",
        "зафиксирован",
        "закрыт",
        "можно переходить",
        "не раскрыт",
        "не указан",
        "не указано",
        "не хватает",
        "отсутствует",
        "упомянут",
        "в тексте нет",
        "не видно,",
    )
    if any(marker in folded for marker in status_markers):
        return True
    question_markers = (
        "как ",
        "какой",
        "какая",
        "какие",
        "где ",
        "когда ",
        "что ",
        "уточните",
        "опишите",
        "расскажите",
        "относится",
    )
    return not any(marker in folded for marker in question_markers)


def _force_gap_question(parsed: dict, draft: RegulationCreationDraft) -> None:
    fallback = question_for_selected_processes(draft.interview_json)
    if fallback is None:
        return
    parsed["status"] = "need_more"
    parsed["message"] = fallback.message
    parsed["quickAnswers"] = list(fallback.quick_answers)
    parsed["nextQuestion"] = {
        "processId": fallback.function_id,
        "field": fallback.field,
        "targetFact": fallback.field,
        "text": fallback.message,
    }
    pipeline = parsed.get("pipeline") if isinstance(parsed.get("pipeline"), dict) else {}
    chosen_ids = selected_process_ids(draft.interview_json)
    parsed["pipeline"] = {
        **pipeline,
        "stage": "questions",
        "selectedProcessIds": chosen_ids,
    }
    draft.interview_json = merge_agent_payload(draft.interview_json, parsed)


def _message_content(parsed: dict, raw: str) -> str:
    next_question = parsed.get("nextQuestion") if isinstance(parsed.get("nextQuestion"), dict) else {}
    return (
        str(next_question.get("text") or "").strip()
        or str(parsed.get("message") or "").strip()
        or leading_question_text(raw)
        or raw
        or "Уточните, пожалуйста, детали процесса."
    )


def _message_function_id(parsed: dict, state: object) -> str:
    answer = parsed.get("answerSufficiency") if isinstance(parsed.get("answerSufficiency"), dict) else {}
    for raw in (
        answer.get("functionId"),
        answer.get("processId"),
        _first_payload_item_id(parsed, "functions"),
        _first_payload_item_id(parsed, "processes"),
    ):
        text = str(raw or "").strip()
        if text:
            return text
    if isinstance(state, dict):
        current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
        text = str(current.get("functionId") or current.get("processId") or "").strip()
        if text:
            return text
        functions = state.get("functions") if isinstance(state.get("functions"), list) else []
        if len(functions) == 1 and isinstance(functions[0], dict):
            return str(functions[0].get("id") or "").strip()
    return ""


def _infer_field_from_assistant_content(message: str) -> str:
    from app.services.regulation_creation.question_queue import _infer_gap_field_from_context

    return _infer_gap_field_from_context({"message": message}, "")


def _message_field(parsed: dict, state: object) -> str:
    answer = parsed.get("answerSufficiency") if isinstance(parsed.get("answerSufficiency"), dict) else {}
    text = str(answer.get("field") or answer.get("intent") or "").strip()
    if text:
        return text
    if isinstance(state, dict):
        function_id = _message_function_id(parsed, state)
        for func in state.get("functions") or []:
            if not isinstance(func, dict):
                continue
            if function_id and str(func.get("id") or "").strip() != function_id:
                continue
            gaps = func.get("openGaps") if isinstance(func.get("openGaps"), list) else []
            if gaps:
                return str(gaps[0] or "").strip()
        current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
        current_field = str(current.get("field") or current.get("intent") or "").strip()
        if current_field:
            for func in state.get("functions") or []:
                if not isinstance(func, dict):
                    continue
                if function_id and str(func.get("id") or "").strip() != function_id:
                    continue
                gaps = [str(gap) for gap in (func.get("openGaps") or [])]
                if current_field in gaps:
                    return current_field
    return ""


def _first_payload_item_id(parsed: dict, key: str) -> str:
    interview = parsed.get("interview") if isinstance(parsed.get("interview"), dict) else {}
    items = interview.get(key) if isinstance(interview.get(key), list) else []
    if items and isinstance(items[0], dict):
        return str(items[0].get("id") or items[0].get("processId") or items[0].get("functionId") or "").strip()
    return ""


def _is_force_create_message(message: str) -> bool:
    text = message.strip().lower()
    return "принудительно" in text or "создай регламент" in text and "не хватает" in text


def _session(db: Session, draft: RegulationCreationDraft) -> RegulationCreationSession:
    result = None
    if draft.result_regulation_id:
        from app.services.regulation.storage import get_document

        doc = get_document(db, regulation_id=draft.result_regulation_id, user_id=draft.user_id)
        if doc is not None:
            try:
                result = RegulationParseResult.model_validate(doc.result_json)
            except Exception:
                result = None
        if result is None and isinstance(draft.draft_document_json, dict) and draft.draft_document_json:
            result = _result_from_created_document(
                regulation_id=draft.result_regulation_id,
                filename=Path(draft.result_document_path or "regulation.docx").name,
                document=draft.draft_document_json,
            )
    queue_info = queue_snapshot(draft.interview_json if isinstance(draft.interview_json, dict) else {})
    interview_state = normalize_interview_state(draft.interview_json if isinstance(draft.interview_json, dict) else {})
    interview_state = replenish_queue(interview_state, target=FULL_QUEUE_TARGET)
    if isinstance(interview_state, dict):
        interview_state = {**interview_state, "pipeline": sync_remaining_estimate(interview_state)}
        queue_info = queue_snapshot(interview_state)
    pipeline = interview_state.get("pipeline") if isinstance(interview_state.get("pipeline"), dict) else sync_remaining_estimate(
        draft.interview_json if isinstance(draft.interview_json, dict) else {}
    )
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
        resultDocument=draft.draft_document_json or {},
        resultDocumentPath=draft.result_document_path,
        sdkAgentId=interview_sdk_agent_id(draft.interview_json),
        progress=interview_progress(draft.interview_json),
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
            content=_clip_message(content),
            structured_json=structured or {},
        )
    )


def _clip_message(content: str, limit: int = _MESSAGE_CONTENT_LIMIT) -> str:
    text = content or ""
    if len(text) <= limit:
        return text
    return text[: limit - 16] + "\n...[truncated]"


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
