"""Execute a claimed trigger on the server worker (not on each desktop)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.trigger import AgentTrigger
from app.models.workflow import Workflow
from app.services.agent_runtime import AgentRuntimeError, run_agent_task
from app.services.agent_runs import answer_from_result, finish_agent_run, start_agent_run
from app.services.notifications.service import NotificationError, create_notification
from app.schemas.notification import NotificationCreate
from app.services.sessions import (
    RECONNECT_EVIDENCE,
    RECONNECT_RETRY_SEC,
    SKIP_RUN_BODY,
    SKIP_RUN_TITLE,
    current_session_id,
    is_user_online,
)
from app.services.tool_bridge import tool_bridge
from app.services.triggers.check import check_trigger_condition
from app.services.triggers.service import is_workflow_inactive, mark_fired, mark_skipped
from app.services.workflows.cursor_tools import clear_tool_context, set_tool_context
from app.services.workflows.service import WorkflowError

logger = logging.getLogger(__name__)


def execute_scheduled_agent_run(db: Session, *, trigger_id: str) -> dict[str, Any]:
    row = db.get(AgentTrigger, trigger_id)
    if row is None or not row.enabled:
        return {"ok": False, "reason": "disabled"}
    workflow = db.get(Workflow, row.workflow_id)
    if workflow is None or is_workflow_inactive(workflow.local_run):
        return {"ok": False, "reason": "paused"}
    if not is_user_online(row.owner_user_id):
        # Active login session means desktop is likely reconnecting after API restart.
        # Retry soon without the scary "app not launched" toast.
        if current_session_id(row.owner_user_id):
            mark_skipped(
                db,
                user_id=row.owner_user_id,
                trigger_id=trigger_id,
                evidence=RECONNECT_EVIDENCE,
                retry_in_seconds=RECONNECT_RETRY_SEC,
            )
            logger.info(
                "Scheduled trigger %s deferred: desktop reconnecting user=%s",
                trigger_id,
                row.owner_user_id,
            )
            return {"ok": False, "reason": "reconnecting"}
        title = workflow.title or "агент"
        _notify_skipped_run(
            db,
            user_id=row.owner_user_id,
            workflow_id=row.workflow_id,
            agent_title=title,
        )
        mark_skipped(db, user_id=row.owner_user_id, trigger_id=trigger_id, evidence=SKIP_RUN_BODY)
        logger.info("Scheduled trigger %s skipped: desktop offline user=%s", trigger_id, row.owner_user_id)
        return {"ok": False, "reason": "offline"}

    evidence = ""
    run_id = tool_bridge.new_run_id()
    tool_bridge.register_run(run_id, row.owner_user_id)
    set_tool_context(run_id, row.owner_user_id)
    history_id = ""
    status = "error"
    answer = ""
    events: list[dict] = []

    def emit(payload: dict) -> None:
        if isinstance(payload, dict):
            events.append(payload)

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
