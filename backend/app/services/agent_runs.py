from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

STALE_STARTED = timedelta(minutes=25)
OVERLAP_CANCEL_ANSWER = "Агент уже выполняется"
SDK_DEAD_ANSWER = "Cursor SDK не отвечает"
STALE_STARTED_ANSWER = "Запуск не завершился за отведённое время."
USER_CANCEL_ANSWER = "Остановлено пользователем"

_INCOMPLETE_ANSWERS = frozenset(
    {
        OVERLAP_CANCEL_ANSWER.casefold(),
        SDK_DEAD_ANSWER.casefold(),
        STALE_STARTED_ANSWER.casefold(),
        USER_CANCEL_ANSWER.casefold(),
    }
)

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
            status="canceled",
            answer=STALE_STARTED_ANSWER,
            events=row.events_json if isinstance(row.events_json, list) else [],
            message=row.message or "",
        )
    return len(rows)


def _normalize_run_status(status: str) -> str:
    raw = (status or "").strip().lower()
    if raw == "ok":
        return "ok"
    if raw in {"canceled", "cancelled"}:
        return "canceled"
    if raw in {"started", "running"}:
        return "started"
    return "error"


def _is_incomplete_answer(answer: str) -> bool:
    text = (answer or "").strip()
    if not text:
        return True
    key = text.casefold()
    if key in _INCOMPLETE_ANSWERS:
        return True
    return key.startswith(OVERLAP_CANCEL_ANSWER.casefold())


def has_run_result(answer: str) -> bool:
    return bool((answer or "").strip()) and not _is_incomplete_answer(answer)


def effective_run_status(status: str, answer: str = "", *, in_flight: bool = False) -> str:
    """Success only when the run produced a result. Incomplete or canceled -> canceled."""
    raw = (status or "").strip().lower()
    if raw in {"started", "running"} and in_flight:
        return "started"
    if raw in {"canceled", "cancelled"}:
        return "canceled"
    if raw == "error" and (answer or "").strip() and not _is_incomplete_answer(answer):
        return "error"
    if has_run_result(answer):
        return "ok"
    return "canceled"


def _row_in_flight(row: AgentRun) -> bool:
    raw = (row.status or "").strip().lower()
    return raw in {"started", "running"} and row.finished_at is None


def list_started_runs(db: Session, *, user_id: str, workflow_id: str) -> list[AgentRun]:
    wid = (workflow_id or "").strip()
    if not wid:
        return []
    return list(
        db.execute(
            select(AgentRun).where(
                AgentRun.workflow_id == wid,
                AgentRun.user_id == user_id,
                AgentRun.status == "started",
            )
        ).scalars()
    )


def cancel_overlapping_slot(
    db: Session,
    *,
    user_id: str,
    trigger_id: str,
    answer: str = "",
) -> AgentRun:
    """Record a canceled schedule slot and advance the trigger so it does not fire late."""
    from app.services.triggers.service import (
        FIRE_COOLDOWN,
        _as_utc,
        _notify_board,
        get_trigger,
        mark_skipped,
    )

    trigger = get_trigger(db, user_id=user_id, trigger_id=trigger_id)
    slot = _as_utc(trigger.fire_at) or datetime.now(timezone.utc)
    note = (answer or "").strip() or OVERLAP_CANCEL_ANSWER
    existing = list(
        db.execute(
            select(AgentRun).where(
                AgentRun.workflow_id == trigger.workflow_id,
                AgentRun.user_id == user_id,
                AgentRun.trigger_id == trigger.id,
                AgentRun.status == "canceled",
            )
        ).scalars()
    )
    for row in existing:
        started = row.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if abs((started - slot).total_seconds()) <= 120:
            return row
    kind, reason = describe_trigger_reason(trigger, evidence=note)
    row = AgentRun(
        id=str(uuid.uuid4()),
        workflow_id=trigger.workflow_id,
        user_id=user_id,
        message=(trigger.message or "").strip(),
        status="canceled",
        answer=note[:4000],
        source="trigger",
        trigger_id=trigger.id,
        trigger_kind=kind,
        trigger_reason=reason[:2000],
        started_at=slot,
        finished_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    interval = int(trigger.interval_seconds or 0)
    if interval > 0:
        mark_skipped(db, user_id=user_id, trigger_id=trigger.id, evidence=note, advance=True)
    elif trigger.once:
        trigger.enabled = False
        trigger.last_checked_at = datetime.now(timezone.utc)
        trigger.last_evidence = note
        db.add(trigger)
        db.commit()
        _notify_board(db, user_id=user_id, workflow_id=trigger.workflow_id, reason="canceled")
    else:
        trigger.cooldown_until = datetime.now(timezone.utc) + FIRE_COOLDOWN
        trigger.last_checked_at = datetime.now(timezone.utc)
        trigger.last_evidence = note
        db.add(trigger)
        db.commit()
        _notify_board(db, user_id=user_id, workflow_id=trigger.workflow_id, reason="canceled")
    return row


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
    row.answer = (answer or "").strip()[:4000]
    row.status = effective_run_status(_normalize_run_status(status), row.answer, in_flight=False)
    row.finished_at = datetime.now(timezone.utc)
    incoming = slim_run_events(events or [])
    if incoming:
        stored = incoming
    else:
        stored = slim_run_events(row.events_json if isinstance(row.events_json, list) else [])
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


_WAIT_START = frozenset({"human_wait", "question", "hitl"})
_WAIT_END = frozenset({"human_reply"})


def _parse_event_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        stamp = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip().replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def compute_run_timing(
    events: list[Any] | None,
    *,
    started_at: datetime | str | None,
    finished_at: datetime | str | None,
    in_flight: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    start = _parse_event_at(started_at)
    end = _parse_event_at(finished_at)
    empty = {
        "agent_work_ms": 0,
        "human_wait_ms": 0,
        "open_segment": "",
        "open_segment_at": "",
    }
    if start is None:
        return empty

    mode = "agent"
    cursor = start
    agent_ms = 0
    human_ms = 0

    def close_until(at: datetime, next_mode: str) -> None:
        nonlocal mode, cursor, agent_ms, human_ms
        if at < cursor:
            at = cursor
        delta = int((at - cursor).total_seconds() * 1000)
        if delta > 0:
            if mode == "agent":
                agent_ms += delta
            elif mode == "human":
                human_ms += delta
        mode = next_mode
        cursor = at

    for raw in events or []:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip().lower()
        at = _parse_event_at(raw.get("at"))
        if at is None:
            continue
        if kind in _WAIT_START:
            if mode != "human":
                close_until(at, "human")
        elif kind in _WAIT_END or (mode == "human" and kind not in _WAIT_START):
            if mode == "human":
                close_until(at, "agent")

    open_segment = ""
    open_at = ""
    if end is not None:
        close_until(end, "")
    elif in_flight:
        open_segment = mode
        open_at = _iso(cursor)
    elif agent_ms == 0 and human_ms == 0:
        close_until(now or datetime.now(timezone.utc), "")

    if agent_ms == 0 and human_ms == 0 and end is not None:
        agent_ms = max(0, int((end - start).total_seconds() * 1000))

    return {
        "agent_work_ms": agent_ms,
        "human_wait_ms": human_ms,
        "open_segment": open_segment,
        "open_segment_at": open_at,
    }


def slim_run_events(events: list[Any]) -> list[dict[str, Any]]:
    stored: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip()
        if kind in {"", "run", "done"}:
            continue
        item: dict[str, Any] = {"type": kind}
        for key in ("text", "message", "tool", "title", "at", "wait"):
            value = raw.get(key)
            if isinstance(value, str) and value.strip():
                item[key] = value.strip()[:8000]
        request_id = str(raw.get("requestId") or raw.get("request_id") or "").strip()
        if request_id:
            item["requestId"] = request_id[:80]
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
    stored = row.events_json if isinstance(row.events_json, list) else []
    events = stored if include_events else []
    in_flight = _row_in_flight(row)
    timing = compute_run_timing(
        stored,
        started_at=row.started_at,
        finished_at=row.finished_at,
        in_flight=in_flight,
    )
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
        agent_work_ms=int(timing["agent_work_ms"]),
        human_wait_ms=int(timing["human_wait_ms"]),
        open_segment=str(timing["open_segment"] or ""),
        open_segment_at=str(timing["open_segment_at"] or ""),
        events=[item for item in events if isinstance(item, dict)],
    )
