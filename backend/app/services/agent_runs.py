from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

STALE_STARTED = timedelta(minutes=25)

logger = logging.getLogger(__name__)

from app.models.agent_run import AgentRun
from app.models.trigger import AgentTrigger
from app.schemas.workflow import AgentRunOut
from app.services.triggers.service import describe_trigger_reason
from app.services.workflows.service import WorkflowError, _get_owned, _iso


def start_agent_run(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    source: str = "chat",
    trigger_id: str = "",
    evidence: str = "",
) -> AgentRun:
    _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    kind = (source or "chat").strip() or "chat"
    if kind not in {"chat", "trigger"}:
        kind = "chat"
    stored_trigger_id = (trigger_id or "").strip()
    trigger_kind = ""
    trigger_reason = ""
    if kind == "trigger":
        trigger = db.get(AgentTrigger, stored_trigger_id) if stored_trigger_id else None
        if trigger is not None and (trigger.owner_user_id != user_id or trigger.workflow_id != workflow_id):
            trigger = None
        trigger_kind, trigger_reason = describe_trigger_reason(trigger, evidence=evidence)
    row = AgentRun(
        id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        user_id=user_id,
        message=(message or "").strip(),
        status="started",
        source=kind,
        trigger_id=stored_trigger_id,
        trigger_kind=trigger_kind,
        trigger_reason=trigger_reason[:2000],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    _notify_board(db, user_id=user_id, workflow_id=workflow_id, run_id=row.id, status=row.status)
    return row


def save_run_events(db: Session, *, run_id: str, events: list[dict[str, Any]]) -> None:
    row = db.get(AgentRun, run_id)
    if row is None or (row.status or "") != "started":
        return
    row.events_json = slim_run_events(events)
    db.commit()


def fail_stale_started_runs(db: Session, *, user_id: str) -> int:
    cutoff = datetime.now(timezone.utc) - STALE_STARTED
    rows = (
        db.execute(
            select(AgentRun).where(
                AgentRun.user_id == user_id,
                AgentRun.status == "started",
                AgentRun.started_at < cutoff,
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        finish_agent_run(
            db,
            run_id=row.id,
            status="error",
            answer="Запуск не завершился за отведённое время.",
            events=row.events_json if isinstance(row.events_json, list) else [],
            message=row.message or "",
        )
    return len(rows)


def finish_agent_run(
    db: Session,
    *,
    run_id: str,
    status: str,
    answer: str = "",
    events: list[dict[str, Any]] | None = None,
    message: str = "",
) -> None:
    row = db.get(AgentRun, run_id)
    if row is None:
        return
    row.status = "ok" if status == "ok" else "error"
    row.answer = (answer or "").strip()[:4000]
    row.finished_at = datetime.now(timezone.utc)
    stored = slim_run_events(events or [])
    if message.strip() and not any(str(item.get("type") or "") == "user_message" for item in stored):
        stored.insert(0, {"type": "user_message", "text": message.strip()[:8000]})
    row.events_json = stored
    db.commit()
    _notify_board(
        db,
        user_id=row.user_id,
        workflow_id=row.workflow_id,
        run_id=row.id,
        status=row.status,
    )


def list_agent_runs(db: Session, *, user_id: str, workflow_id: str) -> list[AgentRunOut]:
    fail_stale_started_runs(db, user_id=user_id)
    _get_owned(db, user_id=user_id, workflow_id=workflow_id, allow_deleted=True)
    rows = (
        db.execute(
            select(AgentRun)
            .where(AgentRun.workflow_id == workflow_id, AgentRun.user_id == user_id)
            .order_by(AgentRun.started_at.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return [_to_out(row) for row in rows]


def get_agent_run(db: Session, *, user_id: str, workflow_id: str, run_id: str) -> AgentRunOut:
    fail_stale_started_runs(db, user_id=user_id)
    _get_owned(db, user_id=user_id, workflow_id=workflow_id, allow_deleted=True)
    row = db.get(AgentRun, run_id)
    if row is None or row.workflow_id != workflow_id or row.user_id != user_id:
        raise WorkflowError("Запуск не найден", status_code=404)
    return _to_out(row, include_events=True)


def _notify_board(
    db: Session,
    *,
    user_id: str,
    workflow_id: str = "",
    run_id: str = "",
    status: str = "",
) -> None:
    try:
        from app.services.workflows.board_live import push_board_updated

        push_board_updated(
            db,
            user_id=user_id,
            workflow_id=workflow_id,
            run_id=run_id,
            status=status,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Board live notify failed user=%s run=%s", user_id, run_id)


def answer_from_result(result: Any) -> str:
    if isinstance(result, dict):
        text = str(result.get("answer") or result.get("text") or "").strip()
        if text:
            return text
        return str(result)[:400]
    return str(result or "").strip()


def slim_run_events(events: list[Any]) -> list[dict[str, Any]]:
    stored: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip()
        if kind in {"", "run", "done"}:
            continue
        item: dict[str, Any] = {"type": kind}
        for key in ("text", "message", "tool", "title"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                item[key] = value.strip()[:8000]
        arguments = raw.get("arguments")
        if isinstance(arguments, dict):
            item["arguments"] = _clip_json(arguments)
        result = raw.get("result")
        if isinstance(result, dict):
            item["result"] = _clip_json(result)
        for key in ("files", "actions", "notifications"):
            value = raw.get(key)
            if isinstance(value, list) and value:
                item[key] = _clip_json(value)
        stored.append(item)
        if len(stored) >= 300:
            break
    return stored


def _clip_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 24:
                out["…"] = "truncated"
                break
            out[str(key)[:80]] = _clip_json(item, depth=depth + 1)
        return out
    if isinstance(value, list):
        return [_clip_json(item, depth=depth + 1) for item in value[:24]]
    if isinstance(value, str):
        return value[:2000]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:400]


def _to_out(row: AgentRun, *, include_events: bool = False) -> AgentRunOut:
    events = row.events_json if include_events and isinstance(row.events_json, list) else []
    return AgentRunOut(
        id=row.id,
        workflow_id=row.workflow_id,
        message=row.message or "",
        status=row.status or "",
        answer=row.answer or "",
        source=row.source or "chat",
        trigger_id=row.trigger_id or "",
        trigger_kind=row.trigger_kind or "",
        trigger_reason=row.trigger_reason or "",
        started_at=_iso(row.started_at),
        finished_at=_iso(row.finished_at) if row.finished_at else "",
        events=[item for item in events if isinstance(item, dict)],
    )
