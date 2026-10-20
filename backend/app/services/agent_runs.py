from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

STALE_STARTED = timedelta(minutes=25)
OVERLAP_CANCEL_ANSWER = "Агент уже выполняется"
SDK_DEAD_ANSWER = "Cursor SDK не отвечает"
STALE_STARTED_ANSWER = "Запуск не завершился за отведённое время."
USER_CANCEL_ANSWER = "Остановлено пользователем"
MISSING_WORK_RESULT_ANSWER = (
    "Запуск завершился без ## WORK_RESULT и TESTS: PASS — "
    "агент остановился после подготовительных шагов."
)

_INCOMPLETE_ANSWERS = frozenset(
    {
        OVERLAP_CANCEL_ANSWER.casefold(),
        SDK_DEAD_ANSWER.casefold(),
        STALE_STARTED_ANSWER.casefold(),
        USER_CANCEL_ANSWER.casefold(),
    }
)
_WORK_RESULT_HEADER_RE = re.compile(r"(?m)^[ \t]*#{0,6}[ \t]*WORK[ _]?RESULT\b", re.I)
_MISSING_WORK_RESULT_RE = re.compile(
    r"запуск завершился без\s+#*\s*WORK[ _]?RESULT",
    re.I,
)
_TESTS_FAIL_RE = re.compile(r"TESTS:\s*FAIL", re.I)
ANSWER_MAX_CHARS = 32000
_CLOSURE_CHECK_RE = re.compile(r"```closure-check\s*\n[\s\S]*?```", re.I)

logger = logging.getLogger(__name__)


def clip_answer(answer: str) -> str:
    """The registry reads the trailing closure-check block: shorten the text before it, not the block."""
    value = (answer or "").strip()
    if len(value) <= ANSWER_MAX_CHARS:
        return value
    blocks = list(_CLOSURE_CHECK_RE.finditer(value))
    block = blocks[-1].group(0) if blocks else ""
    if not block or len(block) >= ANSWER_MAX_CHARS - 2:
        return value[:ANSWER_MAX_CHARS]
    head = _CLOSURE_CHECK_RE.sub("", value).strip()[: ANSWER_MAX_CHARS - len(block) - 2].rstrip()
    return f"{head}\n\n{block}" if head else block

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
    workflow = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
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
    _notify_run_started(
        db,
        user_id=user_id,
        workflow_id=workflow_id,
        run_id=row.id,
        agent_title=workflow.title or "агент",
    )
    return row


_run_columns: dict[str, bool] = {}


def _run_column_ready(db: Session, column: str) -> bool:
    """Колонка появляется миграцией. Пока её нет, данные не пишем и чтение запусков не ломаем."""
    known = _run_columns.get(column)
    if known is not None:
        return known
    try:
        with db.begin_nested():
            row = db.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = 'agent_runs'
                      AND column_name = :column
                    """
                ),
                {"column": column},
            ).first()
    except SQLAlchemyError:
        _run_columns[column] = False
        return False
    _run_columns[column] = row is not None
    return _run_columns[column]


def _metrics_column_ready(db: Session) -> bool:
    return _run_column_ready(db, "metrics_json")


def _write_context(db: Session, run_id: str, context: dict[str, Any]) -> None:
    if not _run_column_ready(db, "context_json"):
        return
    db.execute(
        text("UPDATE agent_runs SET context_json = CAST(:body AS json) WHERE id = :id"),
        {"id": run_id, "body": json.dumps(slim_run_context(context), ensure_ascii=False)},
    )


def save_run_context(db: Session, *, run_id: str, context: dict[str, Any]) -> None:
    row = db.get(AgentRun, run_id)
    if row is None or not _row_in_flight(row):
        return
    _write_context(db, run_id, context)
    db.commit()


def _write_metrics(db: Session, run_id: str, metrics: list[dict[str, Any]]) -> None:
    if not _metrics_column_ready(db):
        return
    db.execute(
        text("UPDATE agent_runs SET metrics_json = CAST(:body AS json) WHERE id = :id"),
        {"id": run_id, "body": json.dumps(slim_run_metrics(metrics), ensure_ascii=False)},
    )


def read_run_metrics(db: Session, run_id: str) -> list[dict[str, Any]]:
    if not _metrics_column_ready(db):
        return []
    try:
        value = db.execute(
            text("SELECT metrics_json FROM agent_runs WHERE id = :id"),
            {"id": run_id},
        ).scalar()
    except SQLAlchemyError:
        logger.warning("run metrics read failed run=%s", run_id, exc_info=True)
        return []
    return slim_run_metrics(value if isinstance(value, list) else [])


def save_run_metrics(db: Session, *, run_id: str, metrics: list[dict[str, Any]]) -> None:
    row = db.get(AgentRun, run_id)
    if row is None or not _row_in_flight(row):
        return
    _write_metrics(db, run_id, metrics)
    db.commit()


def save_run_events(db: Session, *, run_id: str, events: list[dict[str, Any]]) -> None:
    row = db.get(AgentRun, run_id)
    if row is None or (row.status or "") != "started":
        return
    previous = row.events_json if isinstance(row.events_json, list) else []
    row.events_json = slim_run_events(events)
    db.commit()
    _notify_new_run_waits(db, row, previous=previous, current=row.events_json)


def fail_stale_started_runs(db: Session, *, user_id: str, notify: bool = True) -> int:
    """Close runs abandoned by a crashed desktop.

    Read endpoints call this before serving, where `notify=False` avoids a live
    board push that would recompute the very board being built.
    """
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
            notify=notify,
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


def _is_missing_work_result_answer(answer: str) -> bool:
    return bool(_MISSING_WORK_RESULT_RE.search(answer or ""))


def is_successful_work_answer(answer: str) -> bool:
    """True only for a real WORK_RESULT header, not a mention in an error text."""
    text = (answer or "").strip()
    if not text or _is_incomplete_answer(text) or _is_missing_work_result_answer(text):
        return False
    if _TESTS_FAIL_RE.search(text):
        return False
    return bool(_WORK_RESULT_HEADER_RE.search(text))


def effective_run_status(status: str, answer: str = "", *, in_flight: bool = False) -> str:
    """Success only when the run produced a result. Incomplete or canceled -> canceled."""
    raw = (status or "").strip().lower()
    if raw in {"started", "running"} and in_flight:
        return "started"
    if _is_incomplete_answer(answer):
        return "canceled"
    if _is_missing_work_result_answer(answer):
        return "error"
    if is_successful_work_answer(answer):
        return "ok"
    if raw in {"canceled", "cancelled"}:
        return "canceled"
    if raw == "error":
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
                AgentRun.status == "canceled",
            )
        ).scalars()
    )
    for row in existing:
        if not _is_incomplete_answer(row.answer or ""):
            continue
        started = row.started_at
        if started is None:
            continue
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if abs((started - slot).total_seconds()) <= 120:
            interval = int(trigger.interval_seconds or 0)
            if interval > 0:
                mark_skipped(db, user_id=user_id, trigger_id=trigger.id, evidence=note, advance=True)
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
        events_json=[
            {
                "type": "status",
                "text": (
                    "Слот расписания не запущен: агент уже выполнял другой запуск. "
                    "Журнал этой попытки пуст — ход работы остаётся у того запуска."
                ),
            }
        ],
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
    metrics: list[dict[str, Any]] | None = None,
    context: dict[str, Any] | None = None,
    notify: bool = True,
) -> None:
    row = db.get(AgentRun, run_id)
    if row is None:
        return
    was_open = _row_in_flight(row)
    row.answer = clip_answer(answer)
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
    if metrics is not None:
        _write_metrics(db, row.id, metrics)
    if context is not None:
        _write_context(db, row.id, context)
    db.commit()
    try:
        from app.models.workflow import Workflow
        from app.services.workflows.kpi_calc import maybe_recalc_kpi_after_run

        workflow = db.get(Workflow, row.workflow_id)
        if workflow is not None:
            maybe_recalc_kpi_after_run(db, workflow)
    except Exception:  # noqa: BLE001
        logger.debug("KPI refresh after run failed workflow=%s", row.workflow_id, exc_info=True)
    if notify:
        _notify_board(
            db,
            user_id=row.user_id,
            workflow_id=row.workflow_id,
            run_id=row.id,
            status=row.status,
        )
        if was_open:
            _notify_run_finished(
                db,
                user_id=row.user_id,
                workflow_id=row.workflow_id,
                run_id=row.id,
                status=row.status,
            )


def list_agent_runs(db: Session, *, user_id: str, workflow_id: str) -> list[AgentRunOut]:
    fail_stale_started_runs(db, user_id=user_id, notify=False)
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
    fail_stale_started_runs(db, user_id=user_id, notify=False)
    _get_owned(db, user_id=user_id, workflow_id=workflow_id, allow_deleted=True)
    row = db.get(AgentRun, run_id)
    if row is None or row.workflow_id != workflow_id or row.user_id != user_id:
        raise WorkflowError("Запуск не найден", status_code=404)
    out = _to_out(row, include_events=True)
    out.metrics = read_run_metrics(db, row.id)
    out.calendar_meetings = _calendar_meetings_for(
        db, user_id=user_id, workflow_id=workflow_id
    )
    if out.calendar_meetings and not any(
        str(item.get("tool") or "").strip() == "calendar.show_meetings"
        for item in out.events
        if isinstance(item, dict)
    ):
        out.events.append(
            {
                "type": "tool_call",
                "tool": "calendar.show_meetings",
                "arguments": {"meetings": out.calendar_meetings},
                "result": {
                    "shown": len(out.calendar_meetings),
                    "meetings": out.calendar_meetings,
                },
            }
        )
    return out


def _agent_title(db: Session, workflow_id: str) -> str:
    from app.models.workflow import Workflow

    workflow = db.get(Workflow, workflow_id)
    title = str(getattr(workflow, "title", "") or "").strip()
    return title or "агент"


def _push_run_notification(item: Any) -> None:
    try:
        from app.services.notifications.hub import hub
        from app.services.notifications.service import payload_dict

        hub.schedule_push(item.recipient_user_id, payload_dict(item))
    except Exception:  # noqa: BLE001
        logger.debug("Run inbox push failed", exc_info=True)


def _create_run_inbox(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    run_id: str,
    title: str,
    body: str,
) -> None:
    from app.schemas.notification import NotificationCreate
    from app.services.notifications.service import NotificationError, create_notification

    try:
        item = create_notification(
            db,
            sender_user_id=user_id,
            payload=NotificationCreate(
                recipient_user_id=user_id,
                title=title,
                body=body,
                workflow_id=workflow_id,
                run_id=run_id,
            ),
        )
    except NotificationError as exc:
        logger.warning("Could not store run notification user=%s: %s", user_id, exc)
        return
    _push_run_notification(item)


def _pending_wait_events(events: list[Any]) -> dict[str, dict[str, Any]]:
    pending: dict[str, dict[str, Any]] = {}
    closed: set[str] = set()
    for raw in events:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip().lower()
        request_id = str(raw.get("requestId") or raw.get("request_id") or "").strip()
        status = str(raw.get("status") or "").strip().lower()
        if request_id and (status in {"approved", "rejected"} or raw.get("skipped")):
            closed.add(request_id)
            pending.pop(request_id, None)
            continue
        if kind in {"hitl", "question"} and request_id and request_id not in closed:
            pending[request_id] = raw
    return pending


def _notify_new_run_waits(
    db: Session,
    row: AgentRun,
    *,
    previous: list[Any],
    current: list[Any],
) -> None:
    from app.services.sessions import WAIT_CONFIRM_TITLE

    old_ids = set(_pending_wait_events(previous))
    fresh = [
        event
        for request_id, event in _pending_wait_events(current).items()
        if request_id not in old_ids
    ]
    if not fresh:
        return
    agent_title = _agent_title(db, row.workflow_id)
    for event in fresh:
        tool = str(event.get("tool") or event.get("title") or event.get("text") or "").strip()
        hint = f": {tool}" if tool else ""
        _create_run_inbox(
            db,
            user_id=row.user_id,
            workflow_id=row.workflow_id,
            run_id=row.id,
            title=f"{WAIT_CONFIRM_TITLE} · {agent_title}",
            body=f"Агент «{agent_title}» ожидает подтверждения{hint}. Откройте вкладку «Решения».",
        )


def _notify_run_started(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    run_id: str,
    agent_title: str,
) -> None:
    from app.services.sessions import START_RUN_BODY, START_RUN_TITLE

    _create_run_inbox(
        db,
        user_id=user_id,
        workflow_id=workflow_id,
        run_id=run_id,
        title=f"{START_RUN_TITLE} · {agent_title}",
        body=f"Агент «{agent_title}»: {START_RUN_BODY}",
    )


def _notify_run_finished(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    run_id: str,
    status: str,
) -> None:
    from app.services.sessions import FINISH_RUN_TITLE

    agent_title = _agent_title(db, workflow_id)
    key = (status or "").strip().lower()
    if key in {"error", "failed"}:
        body = f"Агент «{agent_title}» завершил запуск с ошибкой."
    elif key in {"canceled", "cancelled"}:
        body = f"Агент «{agent_title}»: запуск отменён."
    else:
        body = f"Агент «{agent_title}» завершил запуск."
    _create_run_inbox(
        db,
        user_id=user_id,
        workflow_id=workflow_id,
        run_id=run_id,
        title=f"{FINISH_RUN_TITLE} · {agent_title}",
        body=body,
    )


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
# Events that can arrive while entering a wait (askQuestion emits tool_request
# right after question). They must not close the human segment.
_WAIT_HOLD = frozenset({"tool_request", "human_wait", "question", "hitl", "status", "ready"})


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
    """Chess-clock split: only one side accrues time.

    - Run starts on the agent clock.
    - human_wait / question / hitl → stop agent, start human.
    - human_reply → stop human, start agent again.
    - Hold markers (tool_request, …) do not switch the clock.
    Open in-flight segment is returned so the UI can keep ticking the active side.
    """
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
            # Agent asked human — human clock starts (chess switch).
            if mode != "human":
                close_until(at, "human")
        elif kind in _WAIT_END:
            # Human answered — agent clock starts immediately.
            if mode == "human":
                close_until(at, "agent")
        elif kind in _WAIT_HOLD:
            continue
        elif mode == "human":
            # Without human_reply marker, first post-wait agent activity
            # resumes the agent clock (legacy runs).
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

    # No HITL at all → whole span is agent clock.
    # If only human was stamped, residual wall time belongs to the agent.
    if end is not None:
        wall_ms = max(0, int((end - start).total_seconds() * 1000))
        if agent_ms == 0 and human_ms == 0:
            agent_ms = wall_ms
        elif agent_ms == 0 and 0 < human_ms < wall_ms:
            agent_ms = wall_ms - human_ms

    return {
        "agent_work_ms": agent_ms,
        "human_wait_ms": human_ms,
        "open_segment": open_segment,
        "open_segment_at": open_at,
    }


_MAX_RUN_EVENTS = 400
_LOW_VALUE_EVENT_TYPES = {"thinking", "status"}
_MUST_KEEP_EVENT_TYPES = {
    "work_result",
    "final",
    "result",
    "user_message",
    "question",
    "hitl",
    "tool_request",
    "human_wait",
    "human_reply",
}


def _event_must_keep(item: dict[str, Any]) -> bool:
    kind = str(item.get("type") or "").strip().lower()
    if kind in _MUST_KEEP_EVENT_TYPES:
        return True
    return str(item.get("tool") or "").strip() == "calendar.show_meetings"


def _trim_run_events(stored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(stored) <= _MAX_RUN_EVENTS:
        return stored
    kept = list(stored)
    while len(kept) > _MAX_RUN_EVENTS:
        drop_at = next(
            (
                index
                for index, item in enumerate(kept)
                if str(item.get("type") or "").strip().lower() in _LOW_VALUE_EVENT_TYPES
                and not _event_must_keep(item)
            ),
            -1,
        )
        if drop_at < 0:
            drop_at = next(
                (index for index, item in enumerate(kept) if not _event_must_keep(item)),
                -1,
            )
        if drop_at < 0:
            break
        kept.pop(drop_at)
    return kept[-_MAX_RUN_EVENTS:]


def slim_run_events(events: list[Any]) -> list[dict[str, Any]]:
    stored: list[dict[str, Any]] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "").strip()
        if kind in {"", "run", "done"}:
            continue
        item: dict[str, Any] = {"type": kind}
        for key in ("text", "message", "tool", "title", "request_id", "requestId", "error", "status", "at", "wait"):
            value = raw.get(key)
            if not isinstance(value, str) or not value:
                continue
            # Куски ответа модели приходят по токену, пробел — отдельным куском.
            # strip() выбрасывал эти пробелы, и журнал склеивался в одно слово.
            if key == "text":
                item["text"] = value[:8000]
                continue
            if value.strip():
                item[key] = value.strip()[:8000]
        request_id = str(raw.get("requestId") or raw.get("request_id") or "").strip()
        if request_id:
            item["requestId"] = request_id[:80]
        if raw.get("ok") is not None:
            item["ok"] = bool(raw.get("ok"))
        if raw.get("skipped") is not None:
            item["skipped"] = bool(raw.get("skipped"))
        if raw.get("confirm_only") is not None:
            item["confirm_only"] = bool(raw.get("confirm_only"))
        elif raw.get("confirmOnly") is not None:
            item["confirm_only"] = bool(raw.get("confirmOnly"))
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
    return _trim_run_events(_coalesce_stream(stored))


_STREAM_EVENT_TYPES = {"assistant", "thinking", "agent_message"}
_STREAM_TEXT_LIMIT = 64_000
_METRIC_KEYS = ("t", "turn", "cpu", "ram", "ram_mb", "gpu", "disk", "disk_read", "disk_write", "processes", "gen")
_METRIC_LIMIT = 7_200
_SPIKE_METRICS = frozenset({"cpu", "ram", "gpu", "disk"})
_SPIKE_PROCESS_LIMIT = 20
_SPIKE_NAME_CHARS = 120


def _coalesce_stream(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Склеить подряд идущие куски одного ответа, не трогая инструменты между ними."""
    merged: list[dict[str, Any]] = []
    for item in events:
        kind = str(item.get("type") or "")
        last = merged[-1] if merged else None
        if (
            last is not None
            and kind in _STREAM_EVENT_TYPES
            and last.get("type") == kind
            and not item.get("tool")
            and not last.get("tool")
        ):
            text = f"{last.get('text') or ''}{item.get('text') or ''}"
            if len(text) > _STREAM_TEXT_LIMIT:
                text = "…" + text[-_STREAM_TEXT_LIMIT:]
            last["text"] = text
            continue
        merged.append(item)
    return merged


def slim_run_metrics(metrics: list[Any] | None) -> list[dict[str, Any]]:
    """Оставить числовой ряд производительности. Мусор и строки отбрасываются."""
    if not isinstance(metrics, list):
        return []
    stored: list[dict[str, Any]] = []
    for raw in metrics:
        if not isinstance(raw, dict):
            continue
        sample: dict[str, Any] = {}
        for key in _METRIC_KEYS:
            value = raw.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            sample[key] = round(float(value), 3)
        if "t" not in sample:
            continue
        spike = _slim_spike(raw.get("spike"))
        if spike:
            sample["spike"] = spike
        stored.append(sample)
    if len(stored) > _METRIC_LIMIT:
        stored = stored[-_METRIC_LIMIT:]
    return stored


_CONTEXT_TYPES = frozenset({"tools", "user", "thinking", "assistant", "tool_call", "tool_result", "other"})
_CONTEXT_ITEM_LIMIT = 1_000
_CONTEXT_SNAPSHOT_LIMIT = 2_000
_CONTEXT_TEXT_CHARS = 1_500
_CONTEXT_LABEL_CHARS = 200


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return int(value)


def slim_run_context(context: Any) -> dict[str, Any]:
    """Контекст окна модели по шагам: части (items), их порядок и снимки-диапазоны order[from:to]."""
    empty: dict[str, Any] = {"items": {}, "order": [], "snapshots": []}
    if not isinstance(context, dict):
        return empty
    raw_items = context.get("items") if isinstance(context.get("items"), dict) else {}
    items: dict[str, dict[str, Any]] = {}
    for key, raw in list(raw_items.items())[:_CONTEXT_ITEM_LIMIT]:
        if not isinstance(raw, dict) or not isinstance(key, str) or not key:
            continue
        chars = _count(raw.get("chars"))
        if chars is None:
            continue
        kind = str(raw.get("type") or "")
        items[key[:120]] = {
            "id": key[:120],
            "turn": _count(raw.get("turn")) or 0,
            "type": kind if kind in _CONTEXT_TYPES else "other",
            "label": str(raw.get("label") or "")[:_CONTEXT_LABEL_CHARS],
            "chars": chars,
            "text": str(raw.get("text") or "")[:_CONTEXT_TEXT_CHARS],
        }
    raw_order = context.get("order") if isinstance(context.get("order"), list) else []
    order = [key for key in raw_order if isinstance(key, str) and key in items and key != "tools"]
    snapshots: list[dict[str, Any]] = []
    raw_snapshots = context.get("snapshots") if isinstance(context.get("snapshots"), list) else []
    for raw in raw_snapshots[-_CONTEXT_SNAPSHOT_LIMIT:]:
        if not isinstance(raw, dict):
            continue
        start, end = _count(raw.get("from")), _count(raw.get("to"))
        if start is None or end is None or start > end or end > len(order):
            continue
        usage = raw.get("usage")
        kind = str(raw.get("kind") or "")
        snapshots.append(
            {
                "seq": _count(raw.get("seq")) or len(snapshots) + 1,
                "at": str(raw.get("at") or "")[:40],
                "turn": _count(raw.get("turn")) or 0,
                "reason": str(raw.get("reason") or "")[:_CONTEXT_LABEL_CHARS],
                "kind": kind if kind in _CONTEXT_TYPES else "",
                "from": start,
                "to": end,
                "usage": (
                    {key: int(value) for key, value in usage.items() if _count(value) is not None and isinstance(key, str)}
                    if isinstance(usage, dict)
                    else None
                ),
            }
        )
    return {"items": items, "order": order, "snapshots": snapshots}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), 3)


def _slim_spike(raw: Any) -> dict[str, Any] | None:
    """Скачок замера: отметки по метрикам и снимок процессов агента в этот момент."""
    if not isinstance(raw, dict):
        return None
    marks: list[dict[str, Any]] = []
    for item in raw.get("marks") or []:
        if not isinstance(item, dict) or item.get("metric") not in _SPIKE_METRICS:
            continue
        value, baseline = _number(item.get("value")), _number(item.get("baseline"))
        if value is None or baseline is None:
            continue
        marks.append({"metric": item["metric"], "value": value, "baseline": baseline})
    if not marks:
        return None
    listed = raw.get("processes")
    processes: list[dict[str, Any]] = []
    for item in (listed if isinstance(listed, list) else [])[:_SPIKE_PROCESS_LIMIT]:
        if not isinstance(item, dict) or _number(item.get("pid")) is None:
            continue
        processes.append(
            {
                "pid": int(item["pid"]),
                "name": str(item.get("name") or "")[:_SPIKE_NAME_CHARS],
                "cpu": _number(item.get("cpu")) or 0.0,
                "ram_mb": _number(item.get("ram_mb")) or 0.0,
                "gpu": _number(item.get("gpu")),
                "disk": _number(item.get("disk")) or 0.0,
            }
        )
    return {"marks": marks, "processes": processes}


def _calendar_meetings_for(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
) -> list[dict[str, Any]]:
    from app.services.calendar_overlay import list_overlays, normalize_meetings

    rows = list_overlays(db, user_id=user_id, workflow_id=workflow_id)
    if not rows:
        return []
    return normalize_meetings(rows[0].meetings)


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
    status = row.status or ""
    if in_flight and str(timing.get("open_segment") or "") == "human":
        status = "waiting_human"
    elif not in_flight:
        status = effective_run_status(status, row.answer or "", in_flight=False)
    return AgentRunOut(
        id=row.id,
        workflow_id=row.workflow_id,
        message=row.message or "",
        status=status,
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
