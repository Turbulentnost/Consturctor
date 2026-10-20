"""Execute a claimed trigger on the server worker (not on each desktop)."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models.trigger import AgentTrigger
from app.models.workflow import Workflow
from app.services.agent_runtime import AgentRuntimeError, run_agent_task
from app.services.agent_runs import (
    OVERLAP_CANCEL_ANSWER,
    answer_from_result,
    cancel_overlapping_slot,
    finish_agent_run,
    save_run_events,
    start_agent_run,
)
from app.services.desktop_commands import push_desktop_command
from app.services.notifications.hub import hub
from app.services.notifications.service import NotificationError, create_notification
from app.schemas.notification import NotificationCreate
from app.services.sessions import (
    RECONNECT_EVIDENCE,
    RECONNECT_RETRY_SEC,
    SKIP_RUN_BODY,
    SKIP_RUN_TITLE,
    presence_status,
)
from app.services.tool_bridge import tool_bridge
from app.services.triggers.check import check_trigger_condition
from app.services.triggers.service import (
    _as_utc,
    workflow_is_inactive,
    mark_fired,
    mark_skipped,
    command_payload,
    runs_on_server,
    workflow_has_started_run,
)
from app.services.workflows.cursor_tools import clear_tool_context, set_tool_context
from app.services.workflows.service import WorkflowError

logger = logging.getLogger(__name__)


def execute_scheduled_agent_run(db: Session, *, trigger_id: str) -> dict[str, Any]:
    row = db.get(AgentTrigger, trigger_id)
    if row is None or not row.enabled:
        return {"ok": False, "reason": "disabled"}
    workflow = db.get(Workflow, row.workflow_id)
    if workflow is None or workflow_is_inactive(workflow):
        return {"ok": False, "reason": "paused"}
    due = _as_utc(row.fire_at)
    now = datetime.now(timezone.utc)
    if due is not None and due > now + timedelta(seconds=5):
        return {"ok": False, "reason": "not_due"}
    if runs_on_server(workflow):
        started = _start_on_server(db, row, workflow)
        if started is not None:
            return started
    presence = presence_status(row.owner_user_id, client="orchestrator")
    desktop_here = hub.is_online(row.owner_user_id, client="orchestrator")
    if presence != "online" and desktop_here:
        presence = "online"
    if workflow_has_started_run(db, row.workflow_id):
        if presence != "offline":
            command = command_payload(row)
            command["workflow_id"] = row.workflow_id
            command["message"] = (row.message or "").strip()
            command["trigger_id"] = row.id
            command["evidence"] = row.last_evidence or ""
            command["source"] = "trigger"
            command["title"] = (workflow.title or "").strip()
            if push_desktop_command(row.owner_user_id, command):
                logger.info(
                    "Scheduled trigger %s dispatched while a run is started user=%s",
                    trigger_id,
                    row.owner_user_id,
                )
                return {"ok": True, "trigger_id": trigger_id, "dispatched": "desktop"}
        cancel_overlapping_slot(
            db,
            user_id=row.owner_user_id,
            trigger_id=trigger_id,
            answer=OVERLAP_CANCEL_ANSWER,
        )
        logger.info("Scheduled trigger %s canceled: agent already running", trigger_id)
        return {"ok": False, "reason": "already_running"}
    if presence == "offline":
        already = SKIP_RUN_BODY.casefold() in (row.last_evidence or "").casefold()
        if not already:
            title = workflow.title or "агент"
            _notify_skipped_run(
                db,
                user_id=row.owner_user_id,
                workflow_id=row.workflow_id,
                agent_title=title,
            )
        mark_skipped(
            db,
            user_id=row.owner_user_id,
            trigger_id=trigger_id,
            evidence=SKIP_RUN_BODY,
        )
        logger.info("Scheduled trigger %s skipped: desktop offline user=%s", trigger_id, row.owner_user_id)
        return {"ok": False, "reason": "offline"}
    if presence == "unknown" and not desktop_here:
        mark_skipped(
            db,
            user_id=row.owner_user_id,
            trigger_id=trigger_id,
            evidence=RECONNECT_EVIDENCE,
            retry_in_seconds=RECONNECT_RETRY_SEC,
            advance=False,
        )
        logger.info("Scheduled trigger %s waiting for desktop user=%s", trigger_id, row.owner_user_id)
        return {"ok": False, "reason": "reconnect"}
    if presence == "unknown":
        logger.warning("Scheduled trigger %s: desktop presence unknown, attempting run", trigger_id)

    command = command_payload(row)
    command["workflow_id"] = row.workflow_id
    command["message"] = (row.message or "").strip()
    command["trigger_id"] = row.id
    command["evidence"] = row.last_evidence or ""
    command["source"] = "trigger"
    command["title"] = (workflow.title or "").strip()
    if push_desktop_command(row.owner_user_id, command):
        if not (row.condition_text or "").strip():
            mark_fired(
                db,
                user_id=row.owner_user_id,
                trigger_id=trigger_id,
                evidence=row.last_evidence or "dispatched to desktop",
            )
        logger.info("Scheduled trigger %s dispatched to desktop user=%s", trigger_id, row.owner_user_id)
        return {"ok": True, "trigger_id": trigger_id, "dispatched": "desktop"}

    evidence = ""
    run_id = tool_bridge.new_run_id()
    tool_bridge.register_run(run_id, row.owner_user_id)
    set_tool_context(run_id, row.owner_user_id)
    history_id = ""
    status = "error"
    answer = ""
    events: list[dict] = []

    def emit(payload: dict) -> None:
        if not isinstance(payload, dict):
            return
        events.append(payload)
        if payload.get("type") == "tool_request":
            try:
                from app.services.workflows.tool_live import push_tool_request

                push_tool_request(row.owner_user_id, payload)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to push tool_request for scheduled run")
        if history_id:
            try:
                save_run_events(db, run_id=history_id, events=events)
            except Exception:  # noqa: BLE001
                logger.exception("Failed to persist scheduled run events")

    try:
        if (row.condition_text or "").strip():
            verdict = check_trigger_condition(
                db,
                user_id=row.owner_user_id,
                trigger_id=trigger_id,
                emit=emit,
            )
            if not verdict.get("matched"):
                logger.info(
                    "Scheduled trigger %s not matched: %s",
                    trigger_id,
                    str(verdict.get("evidence") or "")[:200],
                )
                return {"ok": False, "reason": "not_matched", "evidence": verdict.get("evidence")}
            evidence = str(verdict.get("changed") or verdict.get("evidence") or "")

        message = (row.message or "").strip()
        if not message:
            title = workflow.title or "агент"
            message = (
                f"Выполни рабочую задачу агента «{title}» по правилам из его плана "
                "и покажи понятный результат."
            )
        history = start_agent_run(
            db,
            user_id=row.owner_user_id,
            workflow_id=row.workflow_id,
            message=message,
            source="trigger",
            trigger_id=trigger_id,
            evidence=evidence,
        )
        history_id = history.id
        result = run_agent_task(
            db,
            user_id=row.owner_user_id,
            workflow_id=row.workflow_id,
            message=message,
            emit=emit,
            run_id=run_id,
            history_id=history_id,
        )
        status = "ok"
        answer = answer_from_result(result)
        mark_fired(
            db,
            user_id=row.owner_user_id,
            trigger_id=trigger_id,
            evidence=evidence or "запущен",
        )
        return {"ok": True, "trigger_id": trigger_id, "run_id": history_id}
    except (AgentRuntimeError, WorkflowError) as exc:
        answer = getattr(exc, "message", None) or str(exc)
        logger.warning("Scheduled agent run failed trigger=%s: %s", trigger_id, answer)
        return {"ok": False, "reason": answer}
    except Exception as exc:  # noqa: BLE001
        answer = str(exc)
        logger.exception("Scheduled agent run crashed trigger=%s", trigger_id)
        return {"ok": False, "reason": answer}
    finally:
        if history_id:
            finish_agent_run(
                db,
                run_id=history_id,
                status=status,
                answer=answer,
                events=events,
                message=row.message if row is not None else "",
            )
        clear_tool_context()
        tool_bridge.unregister_run(run_id)


_STALE_STARTED_RUN = timedelta(hours=4)


def _fresh_started_run(db: Session, workflow_id: str) -> bool:
    """A started run younger than the longest server run; older ones are crashed leftovers."""
    from sqlalchemy import select

    from app.models.agent_run import AgentRun

    since = datetime.now(timezone.utc) - _STALE_STARTED_RUN
    return (
        db.execute(
            select(AgentRun.id)
            .where(
                AgentRun.workflow_id == workflow_id,
                AgentRun.status == "started",
                AgentRun.started_at >= since,
            )
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def _start_on_server(db: Session, row: AgentTrigger, workflow: Workflow) -> dict[str, Any] | None:
    """Run the agent on this backend. None: this backend cannot, use the desktop path."""
    from app.services.triggers import headless

    reason = headless.unavailable_reason()
    if reason:
        logger.warning("Trigger %s: server run unavailable (%s), using desktop", row.id, reason)
        return None
    if headless.is_running(row.workflow_id) or _fresh_started_run(db, row.workflow_id):
        cancel_overlapping_slot(
            db,
            user_id=row.owner_user_id,
            trigger_id=row.id,
            answer=OVERLAP_CANCEL_ANSWER,
        )
        logger.info("Scheduled trigger %s canceled: agent already running", row.id)
        return {"ok": False, "reason": "already_running"}
    if (row.condition_text or "").strip():
        logger.warning("Trigger %s has a condition: server runs only plain schedules", row.id)
        return None
    title = (workflow.title or "").strip() or "агент"
    message = (row.message or "").strip() or (
        f"Выполни рабочую задачу агента «{title}» по правилам из его плана и покажи понятный результат."
    )
    job = {
        "user_id": row.owner_user_id,
        "workflow_id": row.workflow_id,
        "message": message,
        "trigger_id": row.id,
        "evidence": row.last_evidence or "",
        "title": title,
    }
    mark_fired(db, user_id=row.owner_user_id, trigger_id=row.id, evidence="запущен на сервере")
    threading.Thread(
        target=_server_job,
        kwargs=job,
        name=f"server-run-{row.workflow_id[:8]}",
        daemon=True,
    ).start()
    logger.info("Scheduled trigger %s started on server user=%s", row.id, row.owner_user_id)
    return {"ok": True, "trigger_id": row.id, "dispatched": "server"}


def _server_job(
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    trigger_id: str,
    evidence: str,
    title: str,
) -> None:
    from app.db.session import SessionLocal
    from app.services.triggers import headless

    try:
        headless.run_headless(
            user_id=user_id,
            workflow_id=workflow_id,
            message=message,
            trigger_id=trigger_id,
            evidence=evidence,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Server run failed trigger=%s", trigger_id)
        db = SessionLocal()
        try:
            create_notification(
                db,
                sender_user_id=user_id,
                payload=NotificationCreate(
                    recipient_user_id=user_id,
                    title="Плановый запуск не удался",
                    body=f"Агент «{title}» на сервере: {exc}",
                    workflow_id=workflow_id,
                ),
            )
        except NotificationError as note_exc:
            logger.warning("Could not store server run failure user=%s: %s", user_id, note_exc)
        finally:
            db.close()


def _notify_skipped_run(db: Session, *, user_id: str, workflow_id: str, agent_title: str) -> None:
    body = (
        f"Агент «{agent_title}»: {SKIP_RUN_BODY}"
    )
    try:
        create_notification(
            db,
            sender_user_id=user_id,
            payload=NotificationCreate(
                recipient_user_id=user_id,
                title=SKIP_RUN_TITLE,
                body=body,
                workflow_id=workflow_id,
            ),
        )
    except NotificationError as exc:
        logger.warning("Could not store skip notification user=%s: %s", user_id, exc)
