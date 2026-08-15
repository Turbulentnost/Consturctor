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
from app.models.workflow import Workflow
from app.schemas.workflow import (
    ArtifactItem,
    ArtifactsDownloadResult,
    AttachmentMetaSchema,
    WorkflowHealth,
    WorkflowListItem,
    WorkflowPlanSchema,
    WorkflowSchema,
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
    return [
        WorkflowListItem(
            id=row.id,
            title=row.title,
            phase=row.phase,
            document_name=row.document_name,
            updated_at=_iso(row.updated_at),
            has_local_run=bool(row.local_run),
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

    title = document_name or "Без названия"
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
    db.delete(row)
    db.commit()
    shutil.rmtree(_workflow_dir(workflow_id), ignore_errors=True)


def update_local_run(
    db: Session, *, user_id: str, workflow_id: str, local_run: dict[str, Any]
) -> WorkflowSchema:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    row.local_run = dict(local_run or {})
    db.commit()
    db.refresh(row)
    return _to_schema(row)


WorkflowEventCallback = Callable[[str, str], None]


def plan_workflow(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    on_event: WorkflowEventCallback | None = None,
) -> WorkflowSchema:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    logger.info("Workflow plan start id=%s title=%s", workflow_id, row.title)
    attachments = _load_attachments_payload(workflow_id)
    images = collect_prompt_images(attachments)
    has_text = bool((row.document_text or "").strip())
    if not has_text and not images:
        raise WorkflowError("Нет материалов для планирования — загрузите файлы или заметки.")

    _emit(on_event, "decision", "Изучаю материалы и формирую структуру workflow.")
    prompt = prompts.build_plan_prompt(
        document_text=row.document_text,
        document_name=row.document_name,
        image_count=len(images),
        attachment_names=[str(a.get("name") or "") for a in attachments],
    )
    model = _resolve_model()
    logger.info(
        "Workflow plan creating Cursor agent id=%s model=%s prompt_len=%s images=%s",
        workflow_id,
        model or "-",
        len(prompt or ""),
        len(images),
    )
    try:
        created = cursor_client.create_agent(
            prompt=prompt,
            model_id=model,
            mode="agent",
            name=row.title,
            images=images or None,
        )
    except CursorAgentError as exc:
        raise WorkflowError(exc.message, status_code=exc.status_code) from exc

    agent = created.get("agent") or {}
    run = created.get("run") or {}
    agent_id = str(agent.get("id") or "")
    run_id = str(run.get("id") or "")
    row.plan_agent_id = agent_id
    row.plan_run_id = run_id
    row.phase = "plan"
    db.commit()
    logger.info(
        "Workflow plan agent created id=%s agent=%s run=%s — waiting for stream text",
        workflow_id,
        agent_id,
        run_id,
    )

    _emit(on_event, "decision", "Планировщик запущен, получаю рассуждения агента.")
    phase = _stream_run(agent_id, run_id, on_event=on_event)
    plan = prompts.parse_plan_from_text(phase.text)
    from app.services.plan_run import ensure_runtime

    ensure_runtime(plan)
    row.plan_json = plan.to_dict()
    row.title = plan.title or row.title
    row.phase = "clarify" if plan.unanswered() else "ready"
    db.commit()
    db.refresh(row)
    _emit(on_event, "decision", "План разобран и сохранён.")
    return _to_schema(row)


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
    prompt = prompts.build_clarify_prompt(
        answers=merged_answers,
        plan=plan,
        image_count=len(images),
        image_names=image_names,
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
            created = cursor_client.create_agent(
                prompt=prompt,
                model_id=_resolve_model(),
                mode="agent",
                name=row.title,
                images=images or None,
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

    phase = _stream_run(agent_id, run_id, on_event=on_event)
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
    from app.services.plan_run import ensure_runtime

    ensure_runtime(updated)
    followups = updated.ensure_followups_for_unclear_answers(
        recent_answers=merged_answers,
        prior_questions=plan.open_questions,
    )
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
            row.plan_json = plan.to_dict()
            db.commit()
        prompt = prompts.build_reexecute_prompt(
            plan=plan,
            user_clarification=clarification,
        )
    else:
        prompt = prompts.build_execute_prompt(plan=plan, document_text=row.document_text)

    _emit(on_event, "decision", "Запускаю реализацию workflow.")
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

    phase = _stream_run(agent_id, run_id, on_event=on_event)
    row.last_result = phase.text
    row.branch = phase.branch or row.branch
    row.pr_url = phase.pr_url or row.pr_url
    # Не публикуем в «Мои агенты» автоматически — только после явного Save.
    # can_publish только при TESTS: PASS в результате реализации.
    if phase.status == "FINISHED":
        tests = _tests_status_from_text(phase.text or "")
        local = dict(row.local_run or {})
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
                "Задайте пользователю вопрос в чате (варианты ответа) и после ответа перезапустите сборку.",
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
            _emit(
                on_event,
                "decision",
                "Реализация завершена, но TESTS: PASS не найден. "
                "Задайте вопрос в чате (с вариантами), затем перезапустите. "
                "Без TESTS: PASS сохранить нельзя.",
            )
        row.local_run = local
    else:
        row.phase = "ready"
        local = dict(row.local_run or {})
        local.update({"can_publish": False, "tests_status": "unknown"})
        row.local_run = local
        _emit(on_event, "decision", "Реализация не завершена — можно запустить снова.")
    db.commit()
    db.refresh(row)
    return _to_schema(row)


def publish_workflow(db: Session, *, user_id: str, workflow_id: str) -> WorkflowSchema:
    """Опубликовать проверенный workflow в «Мои агенты» (phase=done)."""
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    if row.phase == "done" and (row.local_run or {}).get("published"):
        return _to_schema(row)
    if row.phase not in {"tested", "ready", "done"}:
        raise WorkflowError("Сначала завершите реализацию и тесты")
    if not row.exec_agent_id:
        raise WorkflowError("Нет результата реализации для публикации")

    local = dict(row.local_run or {})
    tests = str(local.get("tests_status") or "").casefold()
    if tests != "pass":
        tests = _tests_status_from_text(row.last_result or "")
    if tests == "fail":
        raise WorkflowError("Нельзя сохранить агента: TESTS: FAIL")
    if tests != "pass":
        raise WorkflowError(
            "Нельзя сохранить агента без прохождения тестов (нужен TESTS: PASS)"
        )

    # Published agents run only via in-app MCP runtime (no bat/terminal/code UI).
    for key in ("cwd", "bat", "module", "output", "cmd", "shell"):
        local.pop(key, None)
    plan = WorkflowPlan.from_dict(row.plan_json or {})
    local.update(
        {
            "status": "published",
            "can_publish": False,
            "published": True,
            "tests_status": "pass",
            "runtime": "mcp",
            "tools": _tools_for_published_plan(plan, row),
            "ui_mode": "chat",
        }
    )
    row.local_run = local
    row.phase = "done"
    db.commit()
    db.refresh(row)
    logger.info("Workflow published id=%s title=%s", workflow_id, row.title)
    return _to_schema(row)


def _tests_status_from_text(text: str) -> str:
    """Return pass|fail|unknown from RESULT / agent output."""
    upper = (text or "").upper()
    if "TESTS: FAIL" in upper or "TESTS:FAIL" in upper:
        return "fail"
    if "TESTS: PASS" in upper or "TESTS:PASS" in upper:
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
        any(tip in blob for tip in ("1с", "1c", "onec", "odata"))
        and not any(tip in blob for tip in ("outlook", "календар", "совещан"))
    ):
        return ["onec.odata_get", "onec.sql_query"]

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
        if any(tip in blob for tip in ("1с", "1c", "onec", "odata")):
            tools.extend(["onec.odata_get", "onec.sql_query"])
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
    model = _resolve_model()
    logger.info(
        "Workflow execute creating Cursor agent title=%s model=%s prompt_len=%s",
        title,
        model or "-",
        len(prompt or ""),
    )
    created = cursor_client.create_agent(
        prompt=prompt,
        model_id=model,
        mode="agent",
        name=title,
    )
    agent_id = str((created.get("agent") or {}).get("id") or "")
    run_id = str((created.get("run") or {}).get("id") or "")
    if not agent_id or not run_id:
        raise CursorAgentError("Cursor API не вернул agent/run id")
    return agent_id, run_id


def _resolve_model() -> str | None:
    preferred = settings.cursor_workflow_model
    logger.info("Cursor resolve model preferred=%s", preferred or "-")
    try:
        models = cursor_client.list_models()
    except CursorAgentError as exc:
        logger.warning("Cursor list_models failed: %s — fallback=%s", exc.message, preferred or "-")
        return preferred or None
    ids: list[str] = []
    for model in models:
        mid = str(model.get("id") or "")
        if mid:
            ids.append(mid)
        aliases = {str(a) for a in (model.get("aliases") or [])}
        if preferred and (mid == preferred or preferred in aliases):
            logger.info("Cursor model resolved=%s (preferred match)", mid)
            return mid
    for mid in ids:
        if mid.startswith(preferred or "composer"):
            logger.info("Cursor model resolved=%s (prefix)", mid)
            return mid
    chosen = preferred or (ids[0] if ids else None)
    logger.info("Cursor model resolved=%s from %s candidates", chosen or "-", len(ids))
    return chosen


def _emit(on_event: WorkflowEventCallback | None, event_type: str, text: str) -> None:
    if on_event is not None and text:
        on_event(event_type, text)


def _stream_run(
    agent_id: str,
    run_id: str,
    *,
    on_event: WorkflowEventCallback | None = None,
) -> PhaseResult:
    result = PhaseResult(agent_id=agent_id, run_id=run_id)
    assistant_parts: list[str] = []
    got_terminal = False
    logged_assistant = ""
    logger.info("Cursor stream start agent=%s run=%s", agent_id, run_id)
    try:
        for item in cursor_client.stream_run_events(agent_id, run_id):
            event = str(item.get("event") or "message")
            payload = item.get("data") if isinstance(item.get("data"), dict) else {}
            if event == "assistant":
                chunk = str(payload.get("text") or "")
                if not chunk:
                    continue
                assistant_parts.append(chunk)
                _emit(on_event, "thinking", chunk)
                # Stream may send deltas or cumulative snapshots — log only new text.
                if chunk.startswith(logged_assistant):
                    delta = chunk[len(logged_assistant) :]
                    logged_assistant = chunk
                else:
                    delta = chunk
                    logged_assistant += chunk
                if delta.strip():
                    logger.info("Cursor assistant [%s/%s]: %s", agent_id[-8:], run_id[-8:], delta)
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
        result.text = "".join(assistant_parts).strip()
    if not got_terminal:
        logger.info(
            "Cursor stream incomplete — polling agent=%s run=%s",
            agent_id,
            run_id,
        )
        result = _poll_until_terminal(agent_id, run_id, base=result)
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
    max_wait_s: float = 900.0,
    interval_s: float = 5.0,
) -> PhaseResult:
    result = base
    if not run_id:
        return result
    deadline = time.monotonic() + max_wait_s
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
