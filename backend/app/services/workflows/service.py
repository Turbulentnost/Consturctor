from __future__ import annotations

import logging
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from sqlalchemy.orm import Session

from app.clients import cursor as cursor_client
from app.clients.cursor import CursorAgentError
from app.config import settings

logger = logging.getLogger(__name__)
from app.models.agent_run import AgentRun
from app.models.trigger import AgentTrigger
from app.models.workflow import Workflow
from app.schemas.workflow import (
    ArtifactItem,
    ArtifactsDownloadResult,
    AttachmentMetaSchema,
    AutoRunStopResult,
    WorkflowHealth,
    WorkflowListItem,
    WorkflowPlanSchema,
    WorkflowSchema,
)
from app.services.notifications.service import delete_notifications_for_workflow
from app.services.triggers.service import (
    cancel_triggers_for_workflow,
    delete_triggers_for_workflow,
    is_workflow_paused,
)
from app.services.workflows import prompts
from app.services.workflows.document import (
    DocumentError,
    collect_prompt_images,
    compose_document,
    load_attachment_bytes,
)
from app.services.workflows.plan_models import WorkflowPlan


class WorkflowError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class PhaseResult:
    agent_id: str = ""
    run_id: str = ""
    status: str = ""
    text: str = ""
    branch: str = ""
    pr_url: str = ""
    error: str = ""
    git: dict[str, Any] = field(default_factory=dict)
    successful_live_tools: list[str] = field(default_factory=list)
    step_ledger: list[dict[str, Any]] = field(default_factory=list)


def workflow_health() -> WorkflowHealth:
    try:
        me = cursor_client.get_me()
        who = str(
            me.get("userEmail")
            or me.get("user_email")
            or me.get("apiKeyName")
            or me.get("api_key_name")
            or "ok"
        )
        return WorkflowHealth(ok=True, who=who)
    except CursorAgentError as exc:
        return WorkflowHealth(ok=False, message=exc.message)


def list_workflows(db: Session, *, user_id: str) -> list[WorkflowListItem]:
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id)
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    enabled_ids = {
        str(wid)
        for (wid,) in db.query(AgentTrigger.workflow_id)
        .filter(
            AgentTrigger.owner_user_id == user_id,
            AgentTrigger.enabled.is_(True),
        )
        .distinct()
        .all()
    }
    return [
        WorkflowListItem(
            id=row.id,
            title=row.title,
            phase=row.phase,
            document_name=row.document_name,
            updated_at=_iso(row.updated_at),
            has_local_run=bool(row.local_run),
            auto_run=row.id in enabled_ids and not is_workflow_paused(row.local_run),
            paused=is_workflow_paused(row.local_run),
        )
        for row in rows
    ]


def get_workflow(db: Session, *, user_id: str, workflow_id: str) -> WorkflowSchema:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    return _to_schema(row)


def create_workflow(
    db: Session,
    *,
    user_id: str,
    notes: str,
    files: list[tuple[str, bytes]],
) -> WorkflowSchema:
    workflow_id = str(uuid4())
    storage_dir = _workflow_dir(workflow_id)
    storage_dir.mkdir(parents=True, exist_ok=True)

    attachments: list[dict] = []
    meta: list[dict] = []
    for original_name, raw in files:
        try:
            loaded = load_attachment_bytes(original_name, raw)
        except DocumentError as exc:
            shutil.rmtree(storage_dir, ignore_errors=True)
            raise WorkflowError(str(exc)) from exc
        safe = _safe_filename(original_name)
        stored = storage_dir / safe
        stored.write_bytes(raw)
        loaded["stored_name"] = safe
        loaded["path"] = str(stored)
        attachments.append(loaded)
        meta.append(
            {
                "name": loaded["name"],
                "kind": loaded["kind"],
                "mime_type": loaded.get("mime_type") or "",
                "stored_name": safe,
                "text_preview": (loaded.get("text") or "")[:500],
            }
        )

    document_name, document_text = compose_document(attachments, notes=notes)
    if not document_text.strip() and not any(a.get("kind") == "image" for a in attachments):
        shutil.rmtree(storage_dir, ignore_errors=True)
        raise WorkflowError("Нет материалов — загрузите файлы или заметки.")

    # Persist image base64 in sidecar JSON for later plan calls
    _save_attachments_payload(workflow_id, attachments)

    title = prompts.title_from_materials(
        notes=notes or "",
        document_text=document_text,
        document_name=document_name,
        fallback="ИИ-агент",
    )
    row = Workflow(
        id=workflow_id,
        user_id=user_id,
        title=title,
        phase="document",
        notes=notes or "",
        document_name=document_name,
        document_text=document_text,
        plan_json={},
        attachments_meta=meta,
        local_run={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_schema(row)


def delete_workflow(db: Session, *, user_id: str, workflow_id: str) -> None:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    delete_triggers_for_workflow(db, user_id=user_id, workflow_id=workflow_id)
    delete_notifications_for_workflow(db, workflow_id=workflow_id)
    db.query(AgentRun).filter(AgentRun.workflow_id == workflow_id).delete(synchronize_session=False)
    db.delete(row)
    db.commit()
    shutil.rmtree(_workflow_dir(workflow_id), ignore_errors=True)


def stop_auto_run(db: Session, *, user_id: str, workflow_id: str) -> AutoRunStopResult:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    stopped = cancel_triggers_for_workflow(
        db, user_id=user_id, workflow_id=workflow_id, commit=False
    )
    local = dict(row.local_run or {})
    local["paused"] = True
    row.local_run = local
    db.commit()
    return AutoRunStopResult(ok=True, stopped=stopped)


def update_local_run(
    db: Session, *, user_id: str, workflow_id: str, local_run: dict[str, Any]
) -> WorkflowSchema:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    row.local_run = dict(local_run or {})
    db.commit()
    db.refresh(row)
    return _to_schema(row)


WorkflowEventCallback = Callable[..., None]


def draft_of(row: Workflow) -> dict[str, Any]:
    local = row.local_run if isinstance(row.local_run, dict) else {}
    draft = local.get("playbook_draft")
    return dict(draft) if isinstance(draft, dict) else {}


def _regulation_blob(row: Workflow) -> str:
    return " ".join([row.notes or "", row.document_text or "", row.title or ""])


def _schedule_materials(row: Workflow, draft: dict[str, Any] | None = None) -> str:
    parts = [_regulation_blob(row)]
    data = draft or {}
    if data.get("answers"):
        parts.append(str(data.get("answers") or ""))
    if data.get("when_to_run"):
        parts.append(str(data.get("when_to_run") or ""))
    plan = row.plan_json if isinstance(row.plan_json, dict) else {}
    for item in plan.get("answered_questions") or []:
        if not isinstance(item, dict):
            continue
        parts.append(f"{item.get('question') or ''} {item.get('answer') or ''}")
    return "\n".join(part for part in parts if str(part).strip())


def _validate_and_store_draft(
    db: Session,
    *,
    row: Workflow,
    draft: dict[str, Any],
) -> tuple[dict[str, Any], Any]:
    """Подобрать инструменты по контрактам и проверить полноту черновика."""
    from app.services.workflow_tool_routing import regulation_allows_web
    from app.services.workflows.playbook_validation import (
        attach_tool_candidates,
        validate_draft,
    )

    allow_web = regulation_allows_web(_regulation_blob(row))
    enriched = attach_tool_candidates(draft, allow_web=allow_web)
    validation = validate_draft(
        enriched,
        allow_web=allow_web,
        materials=_schedule_materials(row, enriched),
    )
    local = dict(row.local_run or {})
    local["playbook_draft"] = enriched
    local["draft_validation"] = validation.to_dict()
    row.local_run = local
    db.commit()
    db.refresh(row)
    return enriched, validation


def _emit_config_errors(validation: Any, on_event: WorkflowEventCallback | None) -> None:
    for issue in validation.config_errors:
        detail = f" {issue.detail}" if issue.detail else ""
        _emit(on_event, "decision", f"Ошибка конфигурации агента: {issue.message}{detail}")


def _demo_notes(row: Workflow) -> str:
    notes = str(row.notes or "").strip()
    hint = str((row.local_run or {}).get("retry_hint") or "").strip()
    if not hint:
        return notes
    extra = f"Уточнение после прогона:\n{hint}"
    if extra in notes:
        return notes
    return f"{notes}\n\n{extra}".strip() if notes else extra


def _blocked_before_demo_report(validation: Any, *, message: str = "") -> dict[str, Any]:
    issues = [issue.to_dict() for issue in getattr(validation, "issues", [])]
    reasons = [
        str(issue.get("message") or "")
        for issue in issues
        if str(issue.get("kind") or "") in {"config_error", "ambiguous"}
    ]
    return {
        "ok": False,
        "status": "blocked_before_demo",
        "demo_started": False,
        "can_run_demo": False,
        "message": message or "Пробный прогон не запущен: черновик не прошёл проверку.",
        "reasons": [item for item in reasons if item],
        "issues": issues,
    }


def design_workflow(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    """Спроектировать черновик инструкции; на этой фазе доступен только контекст."""
    from app.services.local_mcp import DESIGN_PHASE
    from app.services.workflows.cursor_tools import (
        contract_vocabulary_block,
        with_tools_if_desktop,
    )

    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    attachments = _load_attachments_payload(workflow_id)
    images = collect_prompt_images(attachments)
    has_text = bool((row.document_text or "").strip() or (row.notes or "").strip())
    if not has_text and not images:
        raise WorkflowError("Нет материалов — загрузите описание бизнес-процесса или файлы.")

    prompt = with_tools_if_desktop(
        prompts.build_playbook_draft_prompt(
            document_text=row.document_text,
            title=row.title,
            notes=row.notes or "",
            document_name=row.document_name,
            vocabulary=contract_vocabulary_block(),
        ),
        phase=DESIGN_PHASE,
    )
    _emit(on_event, "decision", "Проектирую инструкцию по регламенту и проверяю доступный контекст.")
    _emit(on_event, "progress", "пишу черновик инструкции")
    try:
        if row.exec_agent_id:
            try:
                run = cursor_client.create_run(row.exec_agent_id, prompt=prompt, mode="agent")
                agent_id = row.exec_agent_id
                run_id = str(run.get("id") or "")
            except CursorAgentError:
                agent_id, run_id = _create_exec_agent(row.title, prompt)
        else:
            agent_id, run_id = _create_exec_agent(row.title, prompt)
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc

    row.exec_agent_id = agent_id
    row.exec_run_id = run_id
    row.phase = "designing"
    db.commit()

    result = _stream_run_with_tools(
        agent_id,
        run_id,
        on_event=on_event,
        workflow_id=workflow_id,
        mode="execute",
        assistant_as_thinking=True,
        phase=DESIGN_PHASE,
    )
    draft = prompts.parse_playbook_draft(result.text or "")
    draft, validation = _validate_and_store_draft(db, row=row, draft=draft)
    draft, validation = _repair_draft_until_ready(
        db, row=row, draft=draft, validation=validation, on_event=on_event
    )

    return _finish_design(db, row=row, draft=draft, validation=validation, on_event=on_event)


def _needs_draft_repair(validation: Any) -> bool:
    return bool(getattr(validation, "ambiguous", []) or getattr(validation, "config_errors", []))


def _repair_draft_until_ready(
    db: Session,
    *,
    row: Workflow,
    draft: dict[str, Any],
    validation: Any,
    on_event: WorkflowEventCallback | None = None,
    max_attempts: int = 2,
) -> tuple[dict[str, Any], Any]:
    attempts = 0
    while draft.get("steps") and _needs_draft_repair(validation) and attempts < max_attempts:
        attempts += 1
        draft, validation = _repair_draft(
            db,
            row=row,
            draft=draft,
            validation=validation,
            on_event=on_event,
            attempt=attempts,
        )
    return draft, validation


def _repair_draft(
    db: Session,
    *,
    row: Workflow,
    draft: dict[str, Any],
    validation: Any,
    on_event: WorkflowEventCallback | None = None,
    attempt: int = 1,
) -> tuple[dict[str, Any], Any]:
    """Неоднозначные шаги и несовместимые инструменты возвращаем проектировщику."""
    from app.services.local_mcp import DESIGN_PHASE
    from app.services.workflows.cursor_tools import contract_vocabulary_block

    if not row.exec_agent_id:
        return draft, validation
    _emit(
        on_event,
        "decision",
        f"Дорабатываю черновик: нужно уточнить шаги и подобрать совместимые инструменты (попытка {attempt}).",
    )
    prompt = prompts.build_playbook_repair_prompt(
        draft=draft,
        issues=[issue.to_dict() for issue in validation.issues],
        vocabulary=contract_vocabulary_block(),
    )
    try:
        run = cursor_client.create_run(row.exec_agent_id, prompt=prompt, mode="agent")
        run_id = str(run.get("id") or "")
        if not run_id:
            return draft, validation
        result = _stream_run_with_tools(
            row.exec_agent_id,
            run_id,
            on_event=on_event,
            workflow_id=row.id,
            mode="execute",
            assistant_as_thinking=True,
            phase=DESIGN_PHASE,
        )
    except CursorAgentError as exc:
        logger.warning("Draft repair failed id=%s: %s", row.id, exc)
        return draft, validation
    repaired = prompts.parse_playbook_draft(result.text or "")
    if not repaired.get("steps"):
        return draft, validation
    return _validate_and_store_draft(db, row=row, draft=repaired)


def _finish_design(
    db: Session,
    *,
    row: Workflow,
    draft: dict[str, Any],
    validation: Any,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    from app.services.workflows.playbook_validation import issues_to_questions

    local = dict(row.local_run or {})
    local["can_publish"] = False
    local["demo_ok"] = False
    local["validation"] = {
        "ok": True,
        "status": "draft_ready",
        "demo_started": False,
        "can_run_demo": True,
        "issues": [],
        "reasons": [],
    }
    row.local_run = local

    questions = issues_to_questions(validation.issues)
    if questions:
        row.phase = "designed"
        db.commit()
        return _pause_demo_for_questions(
            db,
            row=row,
            phase=PhaseResult(text=""),
            questions=questions,
            on_event=on_event,
        )

    if _needs_draft_repair(validation):
        report = _blocked_before_demo_report(validation)
        local = dict(row.local_run or {})
        local["validation"] = report
        local["can_run_demo"] = False
        row.local_run = local
        _emit_config_errors(validation, on_event)
        for issue in getattr(validation, "ambiguous", []):
            _emit(on_event, "decision", f"Черновик неполный: {issue.message}")
    else:
        local = dict(row.local_run or {})
        local["validation"] = {
            "ok": True,
            "status": "draft_ready",
            "demo_started": False,
            "can_run_demo": True,
            "issues": [],
            "reasons": [],
        }
        local["can_run_demo"] = True
        row.local_run = local
    row.phase = "designed"
    db.commit()
    db.refresh(row)
    if _needs_draft_repair(validation):
        _emit(
            on_event,
            "decision",
            "Черновик не готов к пробному прогону — нужно исправить шаги и инструменты.",
        )
    else:
        steps = len(draft.get("steps") or [])
        _emit(on_event, "decision", f"Черновик инструкции готов: {steps} шагов. Запускаю пробный прогон.")
    return _to_schema(row)


def demo_workflow(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    """Cursor-first: do the business task, then store a playbook for later runs."""
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    attachments = _load_attachments_payload(workflow_id)
    images = collect_prompt_images(attachments)
    has_text = bool((row.document_text or "").strip() or (row.notes or "").strip())
    if not has_text and not images:
        raise WorkflowError("Нет материалов — загрузите описание бизнес-процесса или файлы.")

    draft = draft_of(row)
    if not draft.get("steps"):
        schema = design_workflow(db, user_id=user_id, workflow_id=workflow_id, on_event=on_event)
        db.refresh(row)
        draft = draft_of(row)
        if row.phase == "clarify" or not draft.get("steps"):
            return schema

    draft, validation = _validate_and_store_draft(db, row=row, draft=draft)
    if _needs_draft_repair(validation):
        _emit_config_errors(validation, on_event)
        report = _blocked_before_demo_report(validation)
        local = dict(row.local_run or {})
        local["validation"] = report
        local["demo_ok"] = False
        local["can_publish"] = False
        local["can_run_demo"] = False
        local["tests_status"] = "unknown"
        row.local_run = local
        _emit(
            on_event,
            "decision",
            "Пробный прогон не запущен: черновик не прошёл проверку.",
        )
        row.phase = "designed"
        db.commit()
        db.refresh(row)
        return _to_schema(row)

    from app.services.workflows.cursor_tools import with_tools_if_desktop

    prompt = with_tools_if_desktop(
        prompts.build_demo_prompt(
            document_text=row.document_text,
            title=row.title,
            notes=_demo_notes(row),
            document_name=row.document_name,
            draft=draft,
        ),
        draft=draft,
    )
    _emit(on_event, "decision", "Запускаю пробный прогон по описанию бизнес-процесса.")
    _emit(on_event, "progress", "создаю агента Cursor")
    local_state = dict(row.local_run or {})
    reuse_agent = bool(row.exec_agent_id) and bool(local_state.get("demo_ok"))
    try:
        if reuse_agent:
            try:
                run = cursor_client.create_run(row.exec_agent_id, prompt=prompt, mode="agent")
                agent_id = row.exec_agent_id
                run_id = str(run.get("id") or "")
            except CursorAgentError:
                agent_id, run_id = _create_exec_agent(row.title, prompt)
        else:
            agent_id, run_id = _create_exec_agent(row.title, prompt)
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc

    row.exec_agent_id = agent_id
    row.exec_run_id = run_id
    row.phase = "executing"
    db.commit()
    logger.info("Workflow demo start id=%s agent=%s run=%s", workflow_id, agent_id, run_id)

    phase = _stream_run_with_tools(
        agent_id,
        run_id,
        on_event=on_event,
        workflow_id=workflow_id,
        mode="execute",
        assumption_check=True,
        required_live_tools=_required_demo_tools(row),
        draft=draft,
    )
    return _finish_demo_stream(db, row=row, phase=phase, on_event=on_event)


def plan_workflow(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    schema = design_workflow(
        db, user_id=user_id, workflow_id=workflow_id, on_event=on_event
    )
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    if row.phase == "clarify":
        return schema
    local = dict(row.local_run or {})
    validation = local.get("validation") if isinstance(local.get("validation"), dict) else {}
    blocked = (
        validation.get("status") == "blocked_before_demo"
        or validation.get("can_run_demo") is False
    )
    if blocked or not draft_of(row).get("steps"):
        return schema
    return demo_workflow(
        db, user_id=user_id, workflow_id=workflow_id, on_event=on_event
    )


def clarify_workflow(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    answers: dict[str, str],
    files: list[tuple[str, bytes]] | None = None,
    file_question_ids: list[str] | None = None,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    if not row.plan_json:
        raise WorkflowError("Нет плана для уточнения")

    merged_answers = dict(answers or {})
    attached = _append_attachments(
        db,
        row=row,
        files=files or [],
        file_question_ids=file_question_ids or [],
        answers=merged_answers,
    )
    if attached:
        db.commit()
        db.refresh(row)

    plan = WorkflowPlan.from_dict(row.plan_json)
    plan.record_answers(merged_answers)
    # Несколько вопросов из одного хода — отвечаем по одному, без повторного анализа.
    if plan.unanswered():
        row.plan_json = plan.to_dict()
        row.title = plan.title or row.title
        row.phase = "clarify"
        db.commit()
        db.refresh(row)
        nxt = plan.unanswered()[0]
        _emit(
            on_event,
            "decision",
            f"Ответ учтён. Следующий вопрос: {nxt.question}",
        )
        return _to_schema(row)

    local = dict(row.local_run or {})
    if local.get("awaiting_demo_answers"):
        row.plan_json = plan.to_dict()
        db.commit()
        db.refresh(row)
        return _continue_demo_after_answers(db, row=row, plan=plan, on_event=on_event)

    all_attachments = _load_attachments_payload(workflow_id)
    # Prefer images just attached in this clarify turn; else any stored images.
    if attached:
        wanted = {n.lower() for n in attached}
        clarify_attachments = [
            a
            for a in all_attachments
            if str(a.get("name") or "").lower() in wanted
        ] or all_attachments
    else:
        clarify_attachments = all_attachments
    images = collect_prompt_images(clarify_attachments)
    image_names = [
        str(a.get("name") or "")
        for a in clarify_attachments
        if a.get("kind") == "image" and a.get("name")
    ][: len(images)]
    _emit(on_event, "decision", "Учитываю ответы пользователя и обновляю план.")
    _emit(on_event, "progress", "обновляю план")
    from app.services.workflows.cursor_tools import with_tools_if_desktop

    prompt = with_tools_if_desktop(
        prompts.build_clarify_prompt(
            answers=merged_answers,
            plan=plan,
            image_count=len(images),
            image_names=image_names,
        )
    )
    logger.info(
        "Workflow clarify start id=%s answers=%s images=%s names=%s",
        workflow_id,
        list((merged_answers or {}).keys()),
        len(images),
        image_names,
    )
    try:
        if row.plan_agent_id:
            run = cursor_client.create_run(
                row.plan_agent_id,
                prompt=prompt,
                mode="agent",
                images=images or None,
            )
            agent_id = row.plan_agent_id
            run_id = str(run.get("id") or "")
        else:
            model, model_params = _resolve_model_variant()
            created = cursor_client.create_agent(
                prompt=prompt,
                model_id=model,
                mode="agent",
                name=row.title,
                images=images or None,
                model_params=model_params,
            )
            agent_id = str((created.get("agent") or {}).get("id") or "")
            run_id = str((created.get("run") or {}).get("id") or "")
            row.plan_agent_id = agent_id
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc

    row.plan_run_id = run_id
    db.commit()
    logger.info(
        "Workflow clarify run started id=%s agent=%s run=%s",
        workflow_id,
        agent_id,
        run_id,
    )

    phase = _stream_run_with_tools(
        agent_id, run_id, on_event=on_event, workflow_id=workflow_id, mode="plan"
    )
    updated = prompts.parse_plan_from_text(phase.text)
    prior = {q.id: q.answer for q in plan.open_questions if q.answer}
    for q in updated.open_questions:
        if not q.answer and q.id in prior:
            q.answer = prior[q.id]
    # Durable answers must survive even if the planner returned open_questions: [].
    if not updated.answered_questions and plan.answered_questions:
        updated.answered_questions = list(plan.answered_questions)
    else:
        by_id = {q.id: q for q in updated.answered_questions}
        for q in plan.answered_questions:
            if q.id not in by_id and (q.answer or "").strip():
                updated.answered_questions.append(q)
    updated.record_answers(merged_answers)
    # Keep previous runtime if planner omitted it; then normalize from answers/constraints.
    if not updated.runtime.kind and plan.runtime.kind:
        updated.runtime = plan.runtime
    from app.services.plan_run import apply_autonomy, ensure_runtime

    ensure_runtime(updated)
    apply_autonomy(updated, row.local_run)
    followups = updated.ensure_followups_for_unclear_answers(
        recent_answers=merged_answers,
        prior_questions=plan.open_questions,
    )
    updated.sanitize_open_questions()
    row.plan_json = updated.to_dict()
    row.title = updated.title or row.title
    row.phase = "clarify" if updated.unanswered() else "ready"
    db.commit()
    db.refresh(row)
    if followups or updated.unanswered():
        q = (followups[0] if followups else updated.unanswered()[0]).question
        _emit(
            on_event,
            "decision",
            f"Ответ учтён, но нужно ещё уточнение: {q}",
        )
    else:
        _emit(on_event, "decision", "Уточнения применены к плану — можно собирать.")
    return _to_schema(row)


def execute_workflow(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    reexecute: bool = False,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    if not row.plan_json:
        raise WorkflowError("Нет плана для выполнения")
    plan = WorkflowPlan.from_dict(row.plan_json)
    logger.info(
        "Workflow execute start id=%s reexecute=%s title=%s",
        workflow_id,
        reexecute,
        row.title,
    )

    from app.services.imap_tools import imap_configured
    from app.services.onec_tools import odata_configured
    from app.services.turboproject import turboproject_configured

    access_notes = prompts.server_access_notes(
        odata=odata_configured(),
        imap=imap_configured(),
        turboproject=turboproject_configured(),
    )
    if reexecute:
        clarification = str((row.local_run or {}).get("post_build_answer") or "").strip()
        if clarification:
            from app.services.workflows.plan_models import OpenQuestion

            # Ensure question text is meaningful (not just the id).
            if not any(q.id == "post-build" for q in plan.open_questions):
                plan.open_questions.append(
                    OpenQuestion(
                        id="post-build",
                        question="Уточнение после сборки",
                        why="Блокер TESTS: FAIL",
                    )
                )
            plan.record_answers({"post-build": clarification})
            # Drop temporary open question if it was only for recording.
            plan.open_questions = [q for q in plan.open_questions if q.id != "post-build"]
            from app.services.plan_run import apply_autonomy

            apply_autonomy(plan, row.local_run)
            row.plan_json = plan.to_dict()
            db.commit()
        from app.services.workflows.cursor_tools import with_tools_if_desktop

        prompt = with_tools_if_desktop(
            prompts.build_reexecute_prompt(
                plan=plan,
                user_clarification=clarification,
                access_notes=access_notes,
            )
        )
    else:
        from app.services.workflows.cursor_tools import with_tools_if_desktop

        prompt = with_tools_if_desktop(
            prompts.build_execute_prompt(
                plan=plan,
                document_text=row.document_text,
                access_notes=access_notes,
            )
        )

    _emit(on_event, "decision", "Запускаю реализацию workflow.")
    _emit(on_event, "progress", "создаю агента Cursor")
    try:
        if reexecute and row.exec_agent_id:
            try:
                logger.info(
                    "Workflow execute creating run on existing agent=%s",
                    row.exec_agent_id,
                )
                run = cursor_client.create_run(row.exec_agent_id, prompt=prompt, mode="agent")
                agent_id = row.exec_agent_id
                run_id = str(run.get("id") or "")
            except CursorAgentError:
                agent_id, run_id = _create_exec_agent(row.title, prompt)
        else:
            agent_id, run_id = _create_exec_agent(row.title, prompt)
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc

    row.exec_agent_id = agent_id
    row.exec_run_id = run_id
    row.phase = "executing"
    db.commit()
    logger.info(
        "Workflow execute agent ready id=%s agent=%s run=%s — waiting for stream text",
        workflow_id,
        agent_id,
        run_id,
    )

    from app.services.workflows.cursor_tools import required_live_tools_from_plan

    required_live = required_live_tools_from_plan(plan)
    phase = _stream_run_with_tools(
        agent_id,
        run_id,
        on_event=on_event,
        workflow_id=workflow_id,
        mode="execute",
        required_live_tools=required_live,
    )
    row.last_result = phase.text
    row.branch = phase.branch or row.branch
    row.pr_url = phase.pr_url or row.pr_url
    # Не публикуем в «Мои агенты» автоматически — только после явного Save.
    # can_publish только при TESTS: PASS в результате реализации.
    local = dict(row.local_run or {})
    local["exec_run_status"] = phase.status or ""
    local["odata_configured"] = odata_configured()
    local["imap_configured"] = imap_configured()
    local["live_tools_invoked"] = list(phase.successful_live_tools or [])
    live_ok = bool(phase.successful_live_tools)
    if phase.status == "FINISHED":
        tests = _tests_status_from_text(phase.text or "", live_tools_ok=live_ok)
        if tests == "pass":
            row.phase = "tested"
            local.update(
                {
                    "status": "tested",
                    "can_publish": True,
                    "tests_status": "pass",
                    "runtime": "mcp",
                }
            )
            _emit(
                on_event,
                "decision",
                "Реализация завершена, TESTS: PASS. Можно сохранить агента.",
            )
        elif tests == "fail":
            row.phase = "ready"
            local.update(
                {
                    "status": "tests_failed",
                    "can_publish": False,
                    "tests_status": "fail",
                    "runtime": "mcp",
                }
            )
            _emit(
                on_event,
                "decision",
                "TESTS: FAIL — сохранение недоступно. "
                "Уточните режим проверки в чате (fixtures / COM), без пароля, "
                "и после ответа перезапустите сборку.",
            )
        else:
            row.phase = "ready"
            local.update(
                {
                    "status": "awaiting_tests",
                    "can_publish": False,
                    "tests_status": "unknown",
                    "runtime": "mcp",
                }
            )
            if required_live and not live_ok:
                _emit(
                    on_event,
                    "decision",
                    "Инструмент Constructor ещё не вернул данные. "
                    "Запустите снова — агент должен вызвать constructor_tool, не HTTP с Cloud VM.",
                )
            else:
                _emit(
                    on_event,
                    "decision",
                    "Тестовый прогон завершился без TESTS: PASS. "
                    "Сохранение недоступно. Уточните в чате и перезапустите.",
                )
        row.local_run = local
    else:
        row.phase = "ready"
        local.update({"can_publish": False, "tests_status": "unknown"})
        row.local_run = local
        _emit(on_event, "decision", "Тестовый прогон не завершён — можно запустить снова.")
    db.commit()
    db.refresh(row)
    return _to_schema(row)


def _require_verified_playbook(row: Workflow, playbook: dict[str, Any]) -> None:
    """Публикуем только проверенную инструкцию: черновик и открытые issue не пускаем."""
    local = row.local_run if isinstance(row.local_run, dict) else {}
    draft = local.get("playbook_draft") if isinstance(local.get("playbook_draft"), dict) else {}
    if not draft.get("steps"):
        return
    if str(playbook.get("status") or "") != prompts.DRAFT_STATUS_VERIFIED:
        raise WorkflowError(
            "Нельзя сохранить агента: инструкция ещё черновик, прогон её не подтвердил"
        )
    report = local.get("validation") if isinstance(local.get("validation"), dict) else {}
    if report and not report.get("ok", True):
        reasons = "; ".join(str(item) for item in (report.get("reasons") or []))
        raise WorkflowError(
            "Нельзя сохранить агента: остались незакрытые проверки" + (f" — {reasons}" if reasons else "")
        )
    draft_report = (
        local.get("draft_validation") if isinstance(local.get("draft_validation"), dict) else {}
    )
    if draft_report.get("config_error_count"):
        raise WorkflowError(
            "Нельзя сохранить агента: для части шагов не подобраны инструменты"
        )


def publish_workflow(db: Session, *, user_id: str, workflow_id: str) -> WorkflowSchema:
    """Опубликовать проверенный workflow в «Мои агенты» (phase=done)."""
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    if row.phase == "done" and (row.local_run or {}).get("published"):
        return _to_schema(row)
    playbook = playbook_of(row)
    has_demo = bool(playbook.get("instructions") and playbook.get("demo_ok"))
    if row.phase not in {"tested", "ready", "done", "executing"}:
        raise WorkflowError("Сначала завершите пробный прогон")
    if not row.exec_agent_id and not has_demo:
        raise WorkflowError("Нет результата пробного прогона для публикации")
    _require_verified_playbook(row, playbook)

    local = dict(row.local_run or {})
    if has_demo:
        local["tests_status"] = "pass"
    tests = str(local.get("tests_status") or "").casefold()
    if tests != "pass" and not has_demo:
        tests = _tests_status_from_text(row.last_result or "")
    if tests == "fail" and not has_demo:
        raise WorkflowError("Нельзя сохранить агента: TESTS: FAIL")
    if tests != "pass" and not has_demo:
        raise WorkflowError(
            "Нельзя сохранить агента без успешного пробного прогона"
        )

    # Published agents run only via in-app MCP runtime (no bat/terminal/code UI).
    for key in ("cwd", "bat", "module", "output", "cmd", "shell"):
        local.pop(key, None)
    plan = WorkflowPlan.from_dict(row.plan_json or {})
    draft = local.get("schedule_draft")
    if isinstance(draft, dict):
        name = str(draft.get("name") or "").strip()
        if name:
            row.title = name
        goal = str(draft.get("goal") or "").strip()
        if goal and not (plan.goal or "").strip():
            plan.goal = goal
            row.plan_json = plan.to_dict()
    local.update(
        {
            "status": "published",
            "can_publish": False,
            "published": True,
            "tests_status": "pass",
            "runtime": "cursor" if has_demo else "mcp",
            "tools": _tools_for_published_plan(plan, row),
            "ui_mode": "chat",
            "playbook": playbook or local.get("playbook") or {},
        }
    )
    row.local_run = local
    row.phase = "done"
    db.commit()
    db.refresh(row)
    logger.info("Workflow published id=%s title=%s", workflow_id, row.title)
    return _to_schema(row)


def generate_agent_kpi(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    from app.services import agent_kpi

    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    if not row.exec_agent_id:
        raise WorkflowError("Сначала завершите реализацию агента")
    plan = WorkflowPlan.from_dict(row.plan_json or {})
    local = dict(row.local_run or {})
    draft = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    title = str(draft.get("name") or row.title or plan.title or "ИИ-агент")
    goal = str(draft.get("goal") or plan.goal or "")
    _emit(on_event, "decision", "Куратор определяет KPI: как агент должен работать и как мерить факт.")
    prompt = prompts.build_kpi_curator_prompt(
        title=title,
        goal=goal,
        plan_text=prompts.plan_summary_text(plan),
        schedule_draft=draft,
        notes=row.notes or "",
    )
    text = ""
    try:
        agent_id, run_id = _create_exec_agent(f"KPI · {title}", prompt)
        _emit(on_event, "decision", "Куратор пишет набор KPI…")
        result = _stream_run(agent_id, run_id, on_event=on_event)
        text = result.text or ""
        if result.error:
            _emit(on_event, "decision", "Куратор завершился с предупреждением — сверю JSON и дополню по паспорту.")
    except Exception as exc:  # noqa: BLE001
        logger.warning("KPI curator failed workflow=%s: %s", workflow_id, exc)
        _emit(on_event, "decision", "Куратор недоступен — собрал KPI по паспорту и расписанию.")
    parsed = agent_kpi.parse_kpi_payload(text)
    if parsed:
        _emit(on_event, "decision", "KPI готовы — методика записана, факт посчитает фоновый расчёт.")
    else:
        _emit(on_event, "decision", "Собрал стандартные KPI и методику по расписанию и цели агента.")
    kpi = agent_kpi.build_kpi_record(parsed, title=title, goal=goal, schedule=draft, status="draft")
    local["kpi"] = kpi
    row.local_run = local
    db.commit()
    db.refresh(row)
    return _to_schema(row)


def get_agent_kpi(db: Session, *, user_id: str, workflow_id: str):
    from app.services import agent_kpi

    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    plan = WorkflowPlan.from_dict(row.plan_json or {})
    local = dict(row.local_run or {})
    draft = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    title = str(draft.get("name") or row.title or plan.title or "ИИ-агент")
    goal = str(draft.get("goal") or plan.goal or "")
    stored = local.get("kpi") if isinstance(local.get("kpi"), dict) else None
    if stored and (stored.get("tiles") or []):
        kpi = agent_kpi.build_kpi_record(
            stored,
            title=title,
            goal=goal,
            schedule=draft,
            status=str(stored.get("status") or "draft"),
            generated_at=str(stored.get("generated_at") or ""),
            preserve_runtime=True,
        )
        kpi["summary"] = str(stored.get("summary") or kpi["summary"])
    else:
        kpi = agent_kpi.build_kpi_record(None, title=title, goal=goal, schedule=draft, status="draft")
    return agent_kpi.kpi_to_schema(kpi, workflow_id=workflow_id, title=title)


def confirm_agent_kpi(db: Session, *, user_id: str, workflow_id: str) -> WorkflowSchema:
    from app.services import agent_kpi

    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    local = dict(row.local_run or {})
    stored = local.get("kpi") if isinstance(local.get("kpi"), dict) else None
    if not stored or not (stored.get("tiles") or []):
        plan = WorkflowPlan.from_dict(row.plan_json or {})
        draft = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
        stored = agent_kpi.build_kpi_record(
            None,
            title=str(draft.get("name") or row.title or plan.title or ""),
            goal=str(draft.get("goal") or plan.goal or ""),
            schedule=draft,
            status="draft",
        )
    stored["status"] = "ready"
    local["kpi"] = stored
    row.local_run = local
    db.commit()
    return publish_workflow(db, user_id=user_id, workflow_id=workflow_id)


_VM_INFRA_FAIL_HINTS = (
    "backend_url",
    "constructor_api",
    "cloud vm",
    "нет `backend_url`",
    "нет backend_url",
)


def _is_vm_infra_fail_text(text: str) -> bool:
    low = (text or "").casefold()
    return any(hint in low for hint in _VM_INFRA_FAIL_HINTS)


def playbook_of(row: Workflow | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, dict):
        local = row.get("local_run") if isinstance(row.get("local_run"), dict) else {}
        plan = row.get("plan_json") if isinstance(row.get("plan_json"), dict) else {}
    else:
        local = row.local_run if isinstance(row.local_run, dict) else {}
        plan = row.plan_json if isinstance(row.plan_json, dict) else {}
    playbook = local.get("playbook") if isinstance(local.get("playbook"), dict) else {}
    if not playbook.get("instructions"):
        alt = plan.get("playbook") if isinstance(plan.get("playbook"), dict) else {}
        if alt.get("instructions"):
            playbook = alt
    return dict(playbook)


def _required_demo_tools(row: Workflow, plan: WorkflowPlan | None = None) -> list[str]:
    from app.services.workflows.cursor_tools import wants_notifications

    parts = [row.notes or "", row.document_text or "", row.last_result or ""]
    if plan is None and isinstance(row.plan_json, dict):
        plan = WorkflowPlan.from_dict(row.plan_json)
    if plan is not None:
        parts.append(prompts._answered_scope_lines(plan))
        parts.append(plan.goal or "")
    playbook = playbook_of(row)
    parts.append(str(playbook.get("instructions") or ""))
    return ["notify"] if wants_notifications(*parts) else []


def _answered_scope_of(row: Workflow) -> str:
    if not isinstance(row.plan_json, dict):
        return ""
    plan = WorkflowPlan.from_dict(row.plan_json)
    return prompts._answered_scope_lines(plan)


def _finish_demo_stream(
    db: Session,
    *,
    row: Workflow,
    phase: PhaseResult,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    work = prompts.parse_work_result(phase.text or "")
    row.last_result = work.get("text") or (phase.text or "")[:4000]
    row.branch = phase.branch or row.branch
    draft = draft_of(row)
    questions = prompts.parse_clarify_from_text(phase.text or "")
    if questions and not (draft.get("steps") or []):
        return _pause_demo_for_questions(
            db, row=row, phase=phase, questions=questions, on_event=on_event
        )
    tools = list(phase.successful_live_tools or [])
    report = _demo_validation_report(phase, draft)
    if not report["ok"]:
        return _fail_demo_validation(db, row=row, draft=draft, report=report, on_event=on_event)
    playbook = _refine_playbook(
        row,
        draft=draft,
        demo_text=phase.text or "",
        tools=tools,
        report=report,
        on_event=on_event,
    )
    local = dict(row.local_run or {})
    local["validation"] = report
    local["playbook"] = playbook
    if draft.get("steps"):
        local["playbook_draft"] = {
            **draft,
            "steps": playbook.get("steps") or draft.get("steps"),
            "status": prompts.DRAFT_STATUS_VERIFIED,
        }
    local["demo_ok"] = bool(playbook.get("demo_ok"))
    local["can_publish"] = bool(playbook.get("instructions"))
    local["tests_status"] = "pass" if playbook.get("demo_ok") else "unknown"
    local["live_tools_invoked"] = tools
    local["runtime"] = "cursor"
    local["awaiting_demo_answers"] = False
    local["work_result"] = work
    name = str(playbook.get("name") or "").strip()
    if name and not prompts.is_placeholder_title(name):
        row.title = name
    elif prompts.is_placeholder_title(row.title):
        row.title = prompts.title_from_materials(
            notes=row.notes or "",
            document_text=row.document_text or "",
            document_name=row.document_name or "",
            fallback=row.title or "ИИ-агент",
        )
    from app.services.workflows.schedule_draft import draft_after_demo

    plan_for_scope = (
        WorkflowPlan.from_dict(row.plan_json)
        if isinstance(row.plan_json, dict)
        else None
    )
    local["schedule_draft"] = draft_after_demo(
        title=row.title,
        notes=row.notes or "",
        playbook=playbook,
        last_result=row.last_result or "",
        work=work,
        answered_scope=prompts._answered_scope_lines(plan_for_scope),
    ).model_dump()
    row.local_run = local
    plan_data = dict(row.plan_json) if isinstance(row.plan_json, dict) else {}
    if playbook.get("instructions") and not plan_data.get("title"):
        plan_data["title"] = row.title
        plan_data["goal"] = (row.notes or row.title or "")[:400]
    plan_data["playbook"] = playbook
    row.plan_json = plan_data
    row.phase = "tested" if playbook.get("demo_ok") else "ready"
    db.commit()
    db.refresh(row)
    if playbook.get("demo_ok"):
        _emit(on_event, "decision", "Пробный прогон готов. Сохранил инструкцию для следующих запусков.")
    else:
        _emit(on_event, "decision", "Прогон завершился без устойчивой инструкции — можно запустить снова.")
    return _to_schema(row)


def _pause_demo_for_questions(
    db: Session,
    *,
    row: Workflow,
    phase: PhaseResult,
    questions: list[Any],
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    from app.services.workflows.plan_models import OpenQuestion

    plan = (
        WorkflowPlan.from_dict(row.plan_json)
        if isinstance(row.plan_json, dict)
        else WorkflowPlan()
    )
    plan.title = plan.title or row.title
    plan.goal = plan.goal or (row.notes or row.title or "")[:400]
    plan.raw_text = phase.text or plan.raw_text
    answered_keep = [q for q in plan.open_questions if (q.answer or "").strip()]
    plan.open_questions = answered_keep
    used_ids = {q.id for q in plan.open_questions} | {q.id for q in plan.answered_questions}
    for i, item in enumerate(questions, start=1):
        if not isinstance(item, OpenQuestion):
            continue
        qid = (item.id or "").strip() or f"demo-q{i}"
        if qid in used_ids:
            qid = f"demo-q{len(used_ids) + i}"
        item.id = qid
        plan.open_questions.append(item)
        used_ids.add(qid)
    row.plan_json = plan.to_dict()
    row.phase = "clarify"
    local = dict(row.local_run or {})
    local["awaiting_demo_answers"] = True
    local["demo_ok"] = False
    local["can_publish"] = False
    local["runtime"] = "cursor"
    row.local_run = local
    db.commit()
    db.refresh(row)
    first = plan.unanswered()[0] if plan.unanswered() else questions[0]
    _emit(on_event, "decision", f"Уточнение: {getattr(first, 'question', first)}")
    return _to_schema(row)


def _apply_answers_to_draft(
    db: Session,
    *,
    row: Workflow,
    plan: WorkflowPlan,
) -> tuple[dict[str, Any], Any]:
    """Ответы человека закрывают clarify-пункты черновика, иначе вопрос повторится."""
    draft = draft_of(row)
    if not draft.get("steps"):
        return draft, None
    answers = prompts._answered_scope_lines(plan)
    draft["required_clarifications"] = []
    if answers:
        draft["answers"] = answers
    if not str(draft.get("recipient") or "").strip() and answers:
        draft["recipient"] = "по ответам человека"
    _apply_when_to_run_answer(row, plan, draft)
    return _validate_and_store_draft(db, row=row, draft=draft)


def _apply_when_to_run_answer(row: Workflow, plan: WorkflowPlan, draft: dict[str, Any]) -> None:
    from app.schemas.trigger import ScheduleDraftOut
    from app.services.workflows.schedule_draft import (
        is_when_to_run_question,
        triggers_from_when_answer,
    )

    answer = ""
    for item in plan.answered_questions:
        if is_when_to_run_question(item.question) and (item.answer or "").strip():
            answer = item.answer.strip()
            break
    if not answer:
        return
    draft["when_to_run"] = answer
    local = dict(row.local_run or {})
    current = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    local["schedule_draft"] = ScheduleDraftOut(
        name=str(current.get("name") or row.title or "ИИ-агент"),
        goal=str(current.get("goal") or ""),
        triggers=triggers_from_when_answer(answer),
    ).model_dump()
    row.local_run = local


def _continue_demo_after_answers(
    db: Session,
    *,
    row: Workflow,
    plan: WorkflowPlan,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    from app.services.workflows.cursor_tools import with_tools_if_desktop

    _draft, validation = _apply_answers_to_draft(db, row=row, plan=plan)
    if validation is not None and _needs_draft_repair(validation):
        _emit_config_errors(validation, on_event)
        report = _blocked_before_demo_report(validation)
        local = dict(row.local_run or {})
        local["validation"] = report
        local["demo_ok"] = False
        local["can_publish"] = False
        local["can_run_demo"] = False
        row.local_run = local
        _emit(on_event, "decision", "Пробный прогон не запущен: черновик не прошёл проверку.")
        row.phase = "designed"
        db.commit()
        db.refresh(row)
        return _to_schema(row)

    prompt = with_tools_if_desktop(
        prompts.build_demo_continue_prompt(
            document_text=row.document_text,
            title=row.title,
            notes=_demo_notes(row),
            document_name=row.document_name,
            plan=plan,
            draft=draft_of(row),
        ),
        draft=draft_of(row),
    )
    _emit(on_event, "decision", "Учитываю ответы и продолжаю пробный прогон.")
    _emit(on_event, "progress", "продолжаю прогон")
    try:
        if row.exec_agent_id:
            run = cursor_client.create_run(row.exec_agent_id, prompt=prompt, mode="agent")
            agent_id = row.exec_agent_id
            run_id = str(run.get("id") or "")
        else:
            agent_id, run_id = _create_exec_agent(row.title, prompt)
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc

    row.exec_agent_id = agent_id
    row.exec_run_id = run_id
    row.phase = "executing"
    db.commit()
    phase = _stream_run_with_tools(
        agent_id,
        run_id,
        on_event=on_event,
        workflow_id=row.id,
        mode="execute",
        required_live_tools=_required_demo_tools(row, plan),
        draft=draft_of(row),
    )
    return _finish_demo_stream(db, row=row, phase=phase, on_event=on_event)


def _local_playbook(*, title: str, demo_text: str, tools: list[str], answered_scope: str = "") -> dict[str, Any]:
    summary = (demo_text or "").strip()
    if len(summary) > 2500:
        summary = summary[:2500] + "…"
    tools_line = ", ".join(tools) if tools else "Constructor tools"
    scope = (answered_scope or "").strip()
    scope_line = f"Объём, который выбрал человек:\n{scope}\n" if scope else ""
    instructions = (
        f"Цель: {title or 'выполнить задачу из бизнес-процесса'}.\n"
        f"{scope_line}"
        f"Инструменты, которые уже сработали: {tools_line}.\n"
        "Повтори тот же подход и тот же объём: сначала вызови нужные Constructor tools, "
        "затем дай понятный результат. Не спрашивай про поля и протоколы. "
        "Не расширяй объём до «все», если человек указал конкретное."
    )
    return {
        "instructions": instructions,
        "example_run": summary or "Прогон завершён.",
        "demo_ok": bool(summary or tools),
        "tools": list(tools),
        "name": title or "",
        "expected_result": "",
        "triggers": [],
    }


_ACCEPTED_DATA_STATUS = {"complete", "empty_valid"}


def _demo_validation_report(phase: PhaseResult, draft: dict[str, Any]) -> dict[str, Any]:
    """Гейт итога: успешный прогон — это закрытый ledger, а не наличие текста."""
    ledger = [item for item in (phase.step_ledger or []) if isinstance(item, dict)]
    failed_marker = "FAILED_VALIDATION" in (phase.text or "").upper()
    unfinished = [
        {
            "id": str(item.get("id") or ""),
            "status": str(item.get("status") or ""),
            "data_status": str(item.get("data_status") or ""),
            "tool": str(item.get("tool") or ""),
            "error": str(item.get("error") or ""),
            "reasons": list(item.get("reasons") or []),
        }
        for item in ledger
        if item.get("required") and (
            str(item.get("status") or "") not in {"completed", "skipped"}
            or (
                str(item.get("status") or "") == "completed"
                and str(item.get("data_status") or "") not in _ACCEPTED_DATA_STATUS
            )
        )
    ]
    has_steps = bool(draft.get("steps"))
    ok = not failed_marker and not unfinished and (not has_steps or bool(ledger))
    reasons: list[str] = []
    if failed_marker:
        reasons.append("Агент вернул FAILED_VALIDATION.")
    if unfinished:
        reasons.append(
            "Не закрыты обязательные шаги: "
            + ", ".join(item["id"] for item in unfinished if item["id"])
        )
    if has_steps and not ledger:
        reasons.append("Ни один шаг черновика не подтверждён данными инструментов.")
    return {
        "ok": ok,
        "status": "verified" if ok else "demo_failed",
        "demo_started": True,
        "can_run_demo": True,
        "failed_validation": failed_marker,
        "ledger": ledger,
        "unfinished": unfinished,
        "reasons": reasons,
    }


def _playbook_from_draft(row: Workflow, draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": prompts.DRAFT_STATUS_DRAFT,
        "instructions": prompts.draft_summary_text(draft),
        "example_run": "",
        "demo_ok": False,
        "tools": [],
        "name": row.title or "",
        "expected_result": str(draft.get("result") or ""),
        "triggers": [],
    }


def _fail_demo_validation(
    db: Session,
    *,
    row: Workflow,
    draft: dict[str, Any],
    report: dict[str, Any],
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    """Прогон не подтвердил данные: черновик остаётся, example_run не пишем."""
    stored = {
        **dict(report or {}),
        "ok": False,
        "status": "demo_failed",
        "demo_started": True,
        "can_run_demo": True,
    }
    local = dict(row.local_run or {})
    local["validation"] = stored
    local["playbook"] = _playbook_from_draft(row, draft)
    local["demo_ok"] = False
    local["can_publish"] = False
    local["can_run_demo"] = True
    local["tests_status"] = "fail"
    local["awaiting_demo_answers"] = False
    row.local_run = local
    row.phase = "designed" if draft.get("steps") else "ready"
    db.commit()
    db.refresh(row)
    for reason in report.get("reasons") or []:
        _emit(on_event, "decision", reason)
    _emit(
        on_event,
        "decision",
        "Прогон не подтвердил данные — инструкция осталась черновиком, пример не сохранён.",
    )
    return _to_schema(row)


def _refine_playbook(
    row: Workflow,
    *,
    draft: dict[str, Any],
    demo_text: str,
    tools: list[str],
    report: dict[str, Any],
    on_event: WorkflowEventCallback | None = None,
) -> dict[str, Any]:
    """Правка черновика по фактам прогона, а не первое его создание."""
    if not draft.get("steps"):
        playbook = _distill_playbook(row, demo_text=demo_text, tools=tools, on_event=on_event)
        playbook.setdefault("status", prompts.DRAFT_STATUS_VERIFIED if playbook.get("demo_ok") else prompts.DRAFT_STATUS_DRAFT)
        return playbook

    playbook = _playbook_from_draft(row, draft)
    playbook["tools"] = list(tools)
    playbook["example_run"] = (demo_text or "").strip()[:2500]
    playbook["demo_ok"] = True
    playbook["status"] = prompts.DRAFT_STATUS_VERIFIED
    if not row.exec_agent_id:
        return playbook

    _emit(on_event, "progress", "правлю черновик по итогам прогона")
    try:
        prompt = prompts.build_playbook_refine_prompt(
            draft=draft,
            demo_trace=demo_text,
            validation=report,
            title=row.title,
            tools=tools,
        )
        run = cursor_client.create_run(row.exec_agent_id, prompt=prompt, mode="agent")
        run_id = str(run.get("id") or "")
        if not run_id:
            return playbook
        result = _stream_run(row.exec_agent_id, run_id, on_event=on_event)
        parsed = prompts.parse_playbook_refine(result.text or "", draft=draft)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Playbook refine failed id=%s: %s", row.id, exc)
        return playbook

    if parsed.get("instructions"):
        playbook["instructions"] = parsed["instructions"]
    if parsed.get("example_run"):
        playbook["example_run"] = parsed["example_run"]
    if parsed.get("name") and not prompts.is_placeholder_title(str(parsed.get("name") or "")):
        playbook["name"] = parsed["name"]
    if parsed.get("expected_result"):
        playbook["expected_result"] = parsed["expected_result"]
    if parsed.get("triggers"):
        playbook["triggers"] = parsed["triggers"]
    if parsed.get("steps"):
        playbook["steps"] = parsed["steps"]
    return playbook


def _distill_playbook(
    row: Workflow,
    *,
    demo_text: str,
    tools: list[str],
    on_event: WorkflowEventCallback | None = None,
) -> dict[str, Any]:
    scope = _answered_scope_of(row)
    fallback = _local_playbook(
        title=row.title, demo_text=demo_text, tools=tools, answered_scope=scope
    )
    if not (demo_text or "").strip() and not tools:
        fallback["demo_ok"] = False
        return fallback
    if not row.exec_agent_id:
        return fallback
    _emit(on_event, "progress", "пишу инструкцию по прогону")
    try:
        prompt = prompts.build_playbook_prompt(
            title=row.title,
            demo_text=demo_text,
            tools=tools,
            answered_scope=scope,
        )
        run = cursor_client.create_run(row.exec_agent_id, prompt=prompt, mode="agent")
        run_id = str(run.get("id") or "")
        if not run_id:
            return fallback
        result = _stream_run(row.exec_agent_id, run_id, on_event=on_event)
        parsed = prompts.parse_playbook_from_text(result.text or "")
        if parsed.get("instructions"):
            fallback["instructions"] = parsed["instructions"]
        if parsed.get("example_run"):
            fallback["example_run"] = parsed["example_run"]
        if parsed.get("name") and not prompts.is_placeholder_title(str(parsed.get("name") or "")):
            fallback["name"] = parsed["name"]
        if parsed.get("expected_result"):
            fallback["expected_result"] = parsed["expected_result"]
        if parsed.get("triggers"):
            fallback["triggers"] = parsed["triggers"]
        fallback["demo_ok"] = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Playbook distill failed id=%s: %s", row.id, exc)
    return fallback


def _tests_status_from_text(text: str, *, live_tools_ok: bool = False) -> str:
    """Return pass|fail|unknown from RESULT / agent output."""
    upper = (text or "").upper()
    has_fail = "TESTS: FAIL" in upper or "TESTS:FAIL" in upper
    has_pass = "TESTS: PASS" in upper or "TESTS:PASS" in upper
    if has_fail and _is_vm_infra_fail_text(text) and not live_tools_ok:
        return "unknown"
    if has_fail:
        return "fail"
    if has_pass:
        return "pass"
    return "unknown"


def _tools_for_published_plan(plan: WorkflowPlan, row: Workflow) -> list[str]:
    """Pick MCP tools from plan domain — never force web_search for Outlook/meetings."""
    answered = " ".join(
        f"{q.question} {q.answer}" for q in (plan.answered_questions or []) if q.answer
    )
    blob = " ".join(
        [
            plan.title,
            plan.goal,
            row.title or "",
            row.notes or "",
            " ".join(plan.constraints),
            " ".join(plan.test_criteria),
            answered,
            str(getattr(plan.runtime, "kind", "") or ""),
        ]
    ).casefold()
    kind = str(getattr(plan.runtime, "kind", "") or "").casefold()

    if kind == "onec" or (
        any(tip in blob for tip in ("1с", "1c", "onec", "odata", "erp_pm", "задач"))
        and not any(tip in blob for tip in ("outlook", "календар", "совещан"))
    ):
        return [
            "onec.meeting_service_notes",
            "onec.search_documents",
            "onec.get_document_card",
            "onec.odata_catalog",
            "onec.odata_get",
            "onec.sql_query",
            "onec.erp_tasks_current",
            "onec.erp_tasks_period",
            "onec.erp_subordinate_tasks",
            "onec.docflow_tasks",
            "users.subordinates",
            "turboproject",
        ]

    if kind == "turboproject" or any(
        tip in blob
        for tip in (
            "turboproject",
            "ms project",
            "mpp",
            "портфел проект",
        )
    ):
        return ["turboproject"]

    if kind == "outlook_calendar" or any(
        tip in blob
        for tip in (
            "outlook",
            "календар",
            "совещан",
            "встреч",
            "планирован",
            "занятост",
            "confirm_slot",
            "через com",
            "win32com",
            "outlook.application",
        )
    ):
        # Calendar/meeting agents: no site_browser (that's for web pages, not Outlook).
        # IMAP only if mail is part of the flow; Graph/COM calendar connector TBD.
        tools: list[str] = []
        if any(tip in blob for tip in ("почт", "письм", "imap", "email", "mail")):
            tools.extend(["imap.list_unread", "imap.search"])
        if any(tip in blob for tip in ("1с", "1c", "onec", "odata", "erp_pm", "задач")):
            tools.extend(
                [
                    "onec.meeting_service_notes",
                    "onec.search_documents",
                    "onec.get_document_card",
                    "onec.odata_catalog",
                    "onec.odata_get",
                    "onec.sql_query",
                    "onec.erp_tasks_current",
                    "onec.erp_tasks_period",
                    "onec.erp_subordinate_tasks",
                    "onec.docflow_tasks",
                    "users.subordinates",
                    "turboproject",
                ]
            )
        return tools

    if kind == "site_search_excel" or (
        ("excel" in blob or "xlsx" in blob)
        and ("ключев" in blob or "сайт" in blob or "этп" in blob)
    ):
        return ["site_browser", "plan_export", "web_search"]

    if kind == "browser_task" or "http://" in blob or "https://" in blob:
        return ["site_browser", "web_search"]

    # Generic fallback — still allow search, but browser first.
    return ["site_browser", "web_search", "plan_export"]


def list_artifacts_for_workflow(
    db: Session, *, user_id: str, workflow_id: str
) -> list[ArtifactItem]:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    agent_id = row.exec_agent_id or row.plan_agent_id
    if not agent_id:
        return []
    try:
        items = cursor_client.list_artifacts(agent_id)
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc
    result: list[ArtifactItem] = []
    for it in items:
        path = str(it.get("path") or "")
        if not path:
            continue
        size = it.get("size")
        result.append(ArtifactItem(path=path, size=int(size) if size is not None else None))
    return result


def download_artifacts(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    paths: list[str] | None = None,
) -> ArtifactsDownloadResult:
    """Download Cursor artifacts into backend storage (paths are server-local)."""
    dest, saved = _materialize_artifacts(
        db, user_id=user_id, workflow_id=workflow_id, paths=paths
    )
    return ArtifactsDownloadResult(dest_dir=str(dest), files=saved)


def build_artifacts_zip(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    paths: list[str] | None = None,
) -> Path:
    """Materialize artifacts and pack them into a zip for client download."""
    import zipfile

    dest, saved = _materialize_artifacts(
        db, user_id=user_id, workflow_id=workflow_id, paths=paths
    )
    zip_path = _workflow_dir(workflow_id) / "artifacts.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in saved:
            p = Path(file_path)
            if p.is_file():
                zf.write(p, arcname=p.name)
        if not saved:
            zf.writestr("README.txt", "Артефакты не найдены у Cursor-агента.\n")
    return zip_path


def _materialize_artifacts(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    paths: list[str] | None = None,
) -> tuple[Path, list[str]]:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    agent_id = row.exec_agent_id or row.plan_agent_id
    if not agent_id:
        raise WorkflowError("Нет агента для скачивания артефактов")
    try:
        items = cursor_client.list_artifacts(agent_id)
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc

    wanted = set(paths) if paths else None
    dest = _workflow_dir(workflow_id) / "outputs"
    dest.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []
    for it in items:
        rel = str(it.get("path") or "")
        if not rel:
            continue
        if wanted is not None and rel not in wanted:
            continue
        safe_name = rel.replace("artifacts/", "", 1).replace("/", "_").replace("\\", "_")
        target = dest / safe_name
        try:
            cursor_client.download_artifact_to(agent_id, rel, target)
            saved.append(str(target))
        except CursorAgentError:
            continue
    return dest, saved


def _create_exec_agent(title: str, prompt: str) -> tuple[str, str]:
    model, model_params = _resolve_model_variant()
    logger.info(
        "Workflow execute creating Cursor agent title=%s model=%s params=%s prompt_len=%s",
        title,
        model or "-",
        model_params or "-",
        len(prompt or ""),
    )
    created = cursor_client.create_agent(
        prompt=prompt,
        model_id=model,
        mode="agent",
        name=title,
        model_params=model_params,
    )
    agent_id = str((created.get("agent") or {}).get("id") or "")
    run_id = str((created.get("run") or {}).get("id") or "")
    if not agent_id or not run_id:
        raise CursorAgentError("Cursor API не вернул agent/run id")
    return agent_id, run_id


def _param_value(params: list[Any], param_id: str) -> str:
    for item in params:
        if isinstance(item, dict) and str(item.get("id") or "") == param_id:
            return str(item.get("value") or "").casefold()
    return ""


def _effort_params(record: dict[str, Any] | None, effort: str) -> list[dict[str, str]] | None:
    """Полный вариант модели: API принимает только объявленные id+params."""
    value = (effort or "").strip().casefold()
    if record is None:
        params = [{"id": "effort", "value": value}] if value else []
        params.append({"id": "fast", "value": "true"})
        return params

    variants = [item for item in (record.get("variants") or []) if isinstance(item, dict)]
    matching = [
        variant
        for variant in variants
        if not value or _param_value(list(variant.get("params") or []), "effort") == value
    ]
    if not matching and variants:
        matching = [variant for variant in variants if variant.get("isDefault")] or variants
    chosen = next((variant for variant in matching if variant.get("isDefault")), None) or (
        matching[0] if matching else None
    )
    if chosen is None:
        return None
    params = [
        {"id": str(item.get("id") or ""), "value": str(item.get("value") or "")}
        for item in (chosen.get("params") or [])
        if isinstance(item, dict) and item.get("id")
    ]
    return params or None


def _resolve_model_variant() -> tuple[str | None, list[dict[str, str]] | None]:
    """Id модели и её вариант (например Cursor Grok 4.6 с effort=high)."""
    preferred = settings.cursor_workflow_model
    effort = settings.cursor_workflow_model_effort
    logger.info("Cursor resolve model preferred=%s effort=%s", preferred or "-", effort or "-")
    try:
        models = cursor_client.list_models()
    except CursorAgentError as exc:
        logger.warning("Cursor list_models failed: %s — fallback=%s", exc.message, preferred or "-")
        return (preferred or None), _effort_params(None, effort)

    records = [model for model in models if isinstance(model, dict)]
    ids = [str(model.get("id") or "") for model in records if model.get("id")]
    for model in records:
        mid = str(model.get("id") or "")
        aliases = {str(a) for a in (model.get("aliases") or [])}
        if preferred and (mid == preferred or preferred in aliases):
            logger.info("Cursor model resolved=%s (preferred match)", mid)
            return mid, _effort_params(model, effort)
    if preferred:
        for model in records:
            mid = str(model.get("id") or "")
            if mid.startswith(preferred):
                logger.info("Cursor model resolved=%s (prefix)", mid)
                return mid, _effort_params(model, effort)
    chosen = preferred or (ids[0] if ids else None)
    record = next((m for m in records if str(m.get("id") or "") == chosen), None)
    logger.info("Cursor model resolved=%s from %s candidates", chosen or "-", len(ids))
    return chosen, _effort_params(record, effort)


def _stream_run_with_tools(
    agent_id: str,
    run_id: str,
    *,
    on_event: WorkflowEventCallback | None = None,
    workflow_id: str = "",
    mode: str = "plan",
    required_live_tools: list[str] | None = None,
    assumption_check: bool = False,
    draft: dict[str, Any] | None = None,
    assistant_as_thinking: bool = False,
    phase: str = "execute",
):
    from app.services.workflows.cursor_tools import stream_cursor_with_tools

    def stream_run(agent_id: str, run_id: str, *, on_event=None):
        return _stream_run(
            agent_id,
            run_id,
            on_event=on_event,
            assistant_as_thinking=assistant_as_thinking,
        )

    return stream_cursor_with_tools(
        agent_id=agent_id,
        run_id=run_id,
        on_event=on_event,
        workflow_id=workflow_id,
        mode=mode,
        stream_run=stream_run,
        required_live_tools=required_live_tools,
        assumption_check=assumption_check,
        draft=draft,
        phase=phase,
    )


def _emit(
    on_event: WorkflowEventCallback | None,
    event_type: str,
    text: str = "",
    extra: dict | None = None,
) -> None:
    if on_event is None:
        return
    if extra:
        try:
            on_event(event_type, text, extra)
            return
        except TypeError:
            pass
    if text:
        on_event(event_type, text)


def _cursor_payload_text(payload: dict) -> str:
    for key in ("text", "delta", "message", "content", "thinking"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, dict):
            inner = value.get("text") or value.get("delta") or value.get("content")
            if isinstance(inner, str) and inner:
                return inner
    return ""


def _payload_field_text(payload: dict, *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.replace("\ufffd", "")
        if isinstance(value, dict):
            inner = value.get("text") or value.get("delta") or value.get("content")
            if isinstance(inner, str) and inner.strip():
                return inner.replace("\ufffd", "")
    return ""


def stream_delta(streamed: str, chunk: str) -> str:
    """Хвост нового куска с учётом перекрытия.

    Cursor присылает не только чистое продолжение, но и скользящее окно
    (`ABCD`, затем `CDEF`). Без склейки по overlap текст в ленте заикается.
    """
    if not chunk:
        return ""
    if not streamed:
        return chunk
    if chunk.startswith(streamed):
        return chunk[len(streamed) :]
    if streamed.endswith(chunk) or chunk in streamed:
        return ""
    overlap = min(len(streamed), len(chunk))
    while overlap > 0:
        if streamed.endswith(chunk[:overlap]):
            return chunk[overlap:]
        overlap -= 1
    return chunk


def _cursor_chunks(event: str, payload: dict) -> list[tuple[str, str]]:
    """Split one Cursor SSE event into thinking and/or assistant text."""
    ptype = str(payload.get("type") or payload.get("kind") or "").casefold()
    think = _payload_field_text(payload, "thinking", "reasoning")
    assist = _payload_field_text(payload, "text", "delta", "message", "content")
    event_think = event == "thinking" or ptype in {"thinking", "reasoning"}
    chunks: list[tuple[str, str]] = []
    if think:
        chunks.append(("thinking", think))
        if assist and assist != think:
            chunks.append(("assistant", assist))
        return chunks
    if event_think:
        text = assist or think
        if text:
            chunks.append(("thinking", text))
        return chunks
    if event in {"assistant", "delta", "update", "interaction_update"} and assist:
        chunks.append(("assistant", assist))
    return chunks


def _stream_run(
    agent_id: str,
    run_id: str,
    *,
    on_event: WorkflowEventCallback | None = None,
    assistant_as_thinking: bool = False,
) -> PhaseResult:
    result = PhaseResult(agent_id=agent_id, run_id=run_id)
    assistant_parts: list[str] = []
    thinking_parts: list[str] = []
    got_terminal = False
    streamed_by_kind = {"thinking": "", "assistant": ""}
    logger.info("Cursor stream start agent=%s run=%s", agent_id, run_id)
    try:
        for item in cursor_client.stream_run_events(agent_id, run_id):
            event = str(item.get("event") or "message")
            payload = item.get("data") if isinstance(item.get("data"), dict) else {}
            if event in {"assistant", "thinking", "delta", "update", "interaction_update"}:
                for kind, chunk in _cursor_chunks(event, payload):
                    if not chunk:
                        continue
                    streamed = streamed_by_kind[kind]
                    delta = stream_delta(streamed, chunk)
                    if not delta:
                        continue
                    streamed_by_kind[kind] = streamed + delta
                    if kind == "thinking" or assistant_as_thinking:
                        thinking_parts.append(delta)
                        _emit(on_event, "thinking", delta)
                    else:
                        assistant_parts.append(delta)
                        _emit(on_event, kind, delta)
                    if delta.strip():
                        logger.info("Cursor %s [%s/%s]: %s", kind, agent_id[-8:], run_id[-8:], delta)
            elif event == "message":
                _emit(on_event, "message", str(payload.get("text") or payload.get("message") or ""))
            elif event == "result":
                got_terminal = True
                result.status = str(payload.get("status") or "")
                if payload.get("text"):
                    result.text = str(payload.get("text"))
                result.git = payload.get("git") or {}
                result.branch, result.pr_url = _extract_git(result.git)
                preview = (result.text or "")[:1200]
                logger.info(
                    "Cursor stream result status=%s branch=%s text_len=%s preview=%s",
                    result.status,
                    result.branch or "-",
                    len(result.text or ""),
                    preview,
                )
            elif event == "error":
                result.error = str(payload.get("message") or payload.get("code") or "")
                logger.error(
                    "Cursor stream error agent=%s run=%s: %s",
                    agent_id,
                    run_id,
                    result.error,
                )
            elif event not in {"heartbeat", "ping", "message", "done"}:
                logger.info(
                    "Cursor stream event=%s agent=%s run=%s keys=%s",
                    event,
                    agent_id[-8:],
                    run_id[-8:],
                    sorted(payload.keys()),
                )
    except CursorAgentError as exc:
        logger.warning(
            "Cursor stream failed agent=%s run=%s: %s",
            agent_id,
            run_id,
            exc.message,
        )

    if not result.text:
        assist = "".join(assistant_parts).strip()
        think = "".join(thinking_parts).strip()
        if "constructor_tool" in think and "constructor_tool" not in assist:
            result.text = f"{assist}\n{think}".strip()
        else:
            result.text = assist or think
    if not got_terminal:
        logger.info(
            "Cursor stream incomplete — polling agent=%s run=%s",
            agent_id,
            run_id,
        )
        result = _poll_until_terminal(agent_id, run_id, base=result, on_event=on_event)
        polled = (result.text or "").strip()
        already = streamed_by_kind["assistant"] or "".join(assistant_parts)
        if polled:
            if not already:
                _emit(on_event, "assistant", polled)
            elif polled.startswith(already):
                tail = polled[len(already) :]
                if tail:
                    _emit(on_event, "assistant", tail)
            elif already not in polled:
                _emit(on_event, "assistant", polled)
    logger.info(
        "Cursor stream end agent=%s run=%s status=%s text_len=%s",
        agent_id,
        run_id,
        result.status or "-",
        len(result.text or ""),
    )
    return result


def _poll_until_terminal(
    agent_id: str,
    run_id: str,
    *,
    base: PhaseResult,
    on_event: WorkflowEventCallback | None = None,
    max_wait_s: float = 900.0,
    interval_s: float = 5.0,
) -> PhaseResult:
    result = base
    if not run_id:
        return result
    deadline = time.monotonic() + max_wait_s
    last_progress = 0.0
    while True:
        try:
            run = cursor_client.get_run(agent_id, run_id)
        except CursorAgentError:
            break
        status = str(run.get("status") or "")
        result.status = status or result.status
        if run.get("result"):
            result.text = str(run.get("result"))
        result.git = run.get("git") or result.git
        result.branch, result.pr_url = _extract_git(result.git)
        now = time.monotonic()
        if now - last_progress >= 8.0:
            label = (status or "RUNNING").lower()
            _emit(on_event, "progress", f"агент думает ({label})")
            last_progress = now
        logger.info(
            "Cursor poll agent=%s run=%s status=%s text_len=%s",
            agent_id[-8:],
            run_id[-8:],
            status or "-",
            len(result.text or ""),
        )
        if status in cursor_client.TERMINAL_RUN_STATUSES:
            break
        if time.monotonic() >= deadline:
            logger.warning(
                "Cursor poll timeout agent=%s run=%s last_status=%s",
                agent_id,
                run_id,
                status or "-",
            )
            break
        time.sleep(interval_s)
    return result


def _extract_git(git: dict[str, Any] | None) -> tuple[str, str]:
    if not git:
        return "", ""
    branches = git.get("branches") or []
    if branches and isinstance(branches[0], dict):
        first = branches[0]
        return str(first.get("branch") or ""), str(first.get("prUrl") or first.get("pr_url") or "")
    return "", ""


def _get_owned(db: Session, *, user_id: str, workflow_id: str) -> Workflow:
    row = db.query(Workflow).filter(Workflow.id == workflow_id, Workflow.user_id == user_id).first()
    if row is None:
        raise WorkflowError("Workflow не найден", status_code=404)
    return row


def _workflow_dir(workflow_id: str) -> Path:
    return settings.workflow_storage_dir / workflow_id


def _append_attachments(
    db: Session,
    *,
    row: Workflow,
    files: list[tuple[str, bytes]],
    file_question_ids: list[str],
    answers: dict[str, str],
) -> list[str]:
    """Save clarify attachments and annotate answers with file names."""
    if not files:
        return []

    workflow_id = row.id
    storage_dir = _workflow_dir(workflow_id)
    storage_dir.mkdir(parents=True, exist_ok=True)
    existing = _load_attachments_payload(workflow_id)
    meta = list(row.attachments_meta or [])
    added_names: list[str] = []
    by_question: dict[str, list[str]] = {}

    for idx, (original_name, raw) in enumerate(files):
        try:
            loaded = load_attachment_bytes(original_name, raw)
        except DocumentError as exc:
            raise WorkflowError(str(exc)) from exc
        safe = _safe_filename(original_name)
        # Avoid overwrite collisions
        candidate = storage_dir / safe
        if candidate.exists():
            stem = Path(safe).stem
            suffix = Path(safe).suffix
            safe = f"{stem}_{uuid4().hex[:6]}{suffix}"
            candidate = storage_dir / safe
        candidate.write_bytes(raw)
        loaded["stored_name"] = safe
        loaded["path"] = str(candidate)
        existing.append(loaded)
        meta.append(
            {
                "name": loaded["name"],
                "kind": loaded["kind"],
                "mime_type": loaded.get("mime_type") or "",
                "stored_name": safe,
                "text_preview": (loaded.get("text") or "")[:500],
            }
        )
        added_names.append(loaded["name"])
        qid = ""
        if idx < len(file_question_ids):
            qid = str(file_question_ids[idx] or "").strip()
        if qid:
            by_question.setdefault(qid, []).append(loaded["name"])

    _save_attachments_payload(workflow_id, existing)
    document_name, document_text = compose_document(existing, notes=row.notes or "")
    row.attachments_meta = meta
    row.document_name = document_name or row.document_name
    row.document_text = document_text

    for qid, names in by_question.items():
        note = "Приложенные файлы: " + ", ".join(names)
        prev = (answers.get(qid) or "").strip()
        answers[qid] = f"{prev}\n{note}".strip() if prev else note

    if added_names and not by_question:
        note = "Приложенные файлы: " + ", ".join(added_names)
        if answers:
            first = next(iter(answers.keys()))
            prev = (answers.get(first) or "").strip()
            answers[first] = f"{prev}\n{note}".strip() if prev else note

    return added_names


def _attachments_path(workflow_id: str) -> Path:
    return _workflow_dir(workflow_id) / "attachments_payload.json"


def _save_attachments_payload(workflow_id: str, attachments: list[dict]) -> None:
    import json

    path = _attachments_path(workflow_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep base64 for images; trim huge text duplicates (already in DB)
    slim: list[dict] = []
    for att in attachments:
        item = dict(att)
        if item.get("kind") != "image":
            item["data_b64"] = ""
        slim.append(item)
    path.write_text(json.dumps(slim, ensure_ascii=False), encoding="utf-8")


def _load_attachments_payload(workflow_id: str) -> list[dict]:
    import json

    path = _attachments_path(workflow_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _safe_filename(name: str) -> str:
    base = Path(name).name.replace("..", "_")
    return base or f"file_{uuid4().hex[:8]}"


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _to_schema(row: Workflow) -> WorkflowSchema:
    plan = None
    if row.plan_json:
        plan = WorkflowPlanSchema.model_validate(row.plan_json)
    attachments = [
        AttachmentMetaSchema.model_validate(x)
        for x in (row.attachments_meta or [])
        if isinstance(x, dict)
    ]
    return WorkflowSchema(
        id=row.id,
        title=row.title,
        phase=row.phase,
        notes=row.notes or "",
        document_name=row.document_name or "",
        document_text=row.document_text or "",
        plan=plan,
        attachments=attachments,
        local_run=dict(row.local_run or {}),
        plan_agent_id=row.plan_agent_id or "",
        plan_run_id=row.plan_run_id or "",
        exec_agent_id=row.exec_agent_id or "",
        exec_run_id=row.exec_run_id or "",
        last_result=row.last_result or "",
        branch=row.branch or "",
        pr_url=row.pr_url or "",
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )
