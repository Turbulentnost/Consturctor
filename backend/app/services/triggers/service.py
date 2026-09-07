from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.agent_run import AgentRun
from app.models.trigger import AgentTrigger
from app.models.workflow import Workflow
from app.schemas.trigger import ScheduleTriggerSpec, TriggerCreate, TriggerOut

logger = logging.getLogger(__name__)

CHECK_INTERVAL = timedelta(seconds=45)
FIRE_COOLDOWN = timedelta(seconds=90)


class TriggerError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def is_workflow_paused(local_run: object) -> bool:
    data = local_run if isinstance(local_run, dict) else {}
    return bool(data.get("paused"))


def is_workflow_deleted(local_run: object) -> bool:
    data = local_run if isinstance(local_run, dict) else {}
    return bool(data.get("deleted"))


def workflow_is_deleted(workflow: object) -> bool:
    """Prefer phase=deleted: JSON local_run.deleted can fail to persist on PostgreSQL."""
    if str(getattr(workflow, "phase", "") or "") == "deleted":
        return True
    return is_workflow_deleted(getattr(workflow, "local_run", None))


def is_workflow_inactive(local_run: object) -> bool:
    """Paused or soft-deleted: no new scheduled runs."""
    return is_workflow_paused(local_run) or is_workflow_deleted(local_run)


def workflow_is_inactive(workflow: object) -> bool:
    return workflow_is_deleted(workflow) or is_workflow_paused(getattr(workflow, "local_run", None))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_CLOCK_IN_TEXT = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_MSK = timezone(timedelta(hours=3))


def _clock_hint_from_message(message: str) -> tuple[int, int] | None:
    matches = _CLOCK_IN_TEXT.findall(message or "")
    if not matches:
        return None
    hour, minute = matches[-1]
    return int(hour), int(minute)


def _next_at_msk_clock(clock: tuple[int, int], now: datetime) -> datetime:
    local_now = now.astimezone(_MSK)
    hour, minute = clock
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate = candidate + timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def parse_active_days(value: object) -> set[int]:
    """Accept a list[int] or a comma string like '0,1,2,3,4'. Returns weekday set."""
    days: set[int] = set()
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        items = str(value or "").split(",")
    for item in items:
        try:
            day = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            days.add(day)
    return days


def format_active_days(days: object) -> str:
    parsed = sorted(parse_active_days(days))
    return ",".join(str(d) for d in parsed)


def parse_clock_to_min(value: str) -> int | None:
    """'HH:MM' -> minutes from midnight, or None."""
    raw = (value or "").strip()
    if not raw:
        return None
    match = re.match(r"^\s*([01]?\d|2[0-3])[:.]([0-5]\d)\s*$", raw)
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def format_min_to_clock(value: int | None) -> str:
    if value is None:
        return ""
    value = int(value) % (24 * 60)
    return f"{value // 60:02d}:{value % 60:02d}"


def has_window(window_start_min: int | None, window_end_min: int | None) -> bool:
    return (
        window_start_min is not None
        and window_end_min is not None
        and int(window_end_min) >= int(window_start_min)
    )


def next_windowed_slot(
    after: datetime,
    *,
    interval_seconds: int,
    window_start_min: int,
    window_end_min: int,
    active_days: set[int],
    inclusive: bool = False,
    max_days: int = 400,
) -> datetime | None:
    """First slot on the daily 08:00→17:00 style grid after `after` (MSK)."""
    interval = int(interval_seconds or 0)
    if interval <= 0:
        return None
    step_min = max(1, interval // 60)
    ref = _as_utc(after) or datetime.now(timezone.utc)
    day = ref.astimezone(_MSK).date()
    for _ in range(max_days):
        if not active_days or day.weekday() in active_days:
            minute = int(window_start_min)
            while minute <= int(window_end_min):
                local = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=_MSK)
                candidate = local.astimezone(timezone.utc)
                if (candidate >= ref) if inclusive else (candidate > ref):
                    return candidate
                minute += step_min
        day = day + timedelta(days=1)
    return None


def windowed_slots_between(
    *,
    start: datetime,
    end: datetime,
    interval_seconds: int,
    window_start_min: int,
    window_end_min: int,
    active_days: set[int],
    max_slots: int = 800,
) -> list[datetime]:
    """All grid slots within [start, end] for the daily window (MSK)."""
    interval = int(interval_seconds or 0)
    if interval <= 0:
        return []
    step_min = max(1, interval // 60)
    start_utc = _as_utc(start)
    end_utc = _as_utc(end)
    if start_utc is None or end_utc is None or end_utc < start_utc:
        return []
    day = start_utc.astimezone(_MSK).date()
    last_day = end_utc.astimezone(_MSK).date()
    out: list[datetime] = []
    guard = 0
    while day <= last_day and guard < 500 and len(out) < max_slots:
        guard += 1
        if not active_days or day.weekday() in active_days:
            minute = int(window_start_min)
            while minute <= int(window_end_min) and len(out) < max_slots:
                local = datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=_MSK)
                candidate = local.astimezone(timezone.utc)
                if start_utc <= candidate <= end_utc:
                    out.append(candidate)
                minute += step_min
        day = day + timedelta(days=1)
    return out


def slot_key(value: datetime | None) -> str:
    """Stable UTC minute key used to cancel one calendar slot."""
    stamp = _as_utc(value)
    if stamp is None:
        return ""
    return stamp.replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M")


def parse_skipped_slots(value: object) -> set[str]:
    keys: set[str] = set()
    if not isinstance(value, list):
        return keys
    for item in value:
        raw = str(item or "").strip()
        if not raw:
            continue
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", raw):
                keys.add(raw)
            continue
        key = slot_key(parsed)
        if key:
            keys.add(key)
    return keys


def slot_is_skipped(row: AgentTrigger, when: datetime | None = None) -> bool:
    target = when if when is not None else row.fire_at
    skipped = parse_skipped_slots(getattr(row, "skipped_slots", None))
    if not skipped:
        return False
    return bool(_slot_keys(target) & skipped)


def _slot_keys(value: datetime | None) -> set[str]:
    if value is None:
        return set()
    candidates = [value]
    if value.tzinfo is None:
        candidates = [value.replace(tzinfo=timezone.utc), value.replace(tzinfo=_MSK)]
    keys: set[str] = set()
    for item in candidates:
        key = slot_key(item)
        if key:
            keys.add(key)
        local = item.astimezone(_MSK).replace(second=0, microsecond=0)
        keys.add(local.strftime("%Y-%m-%dT%H:%M"))
        keys.add(item.astimezone(timezone.utc).replace(second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M"))
    return keys


def same_calendar_slot(left: datetime | None, right: datetime | None) -> bool:
    return bool(_slot_keys(left) & _slot_keys(right))


def next_aligned_fire_at(
    fire_at: datetime | None,
    interval_seconds: int,
    *,
    now: datetime | None = None,
    message: str = "",
    active_days: object = None,
    window_start_min: int | None = None,
    window_end_min: int | None = None,
) -> datetime:
    """Keep the original clock grid so a skipped 11:00 slot still exists as missed."""
    now = now or datetime.now(timezone.utc)
    interval = int(interval_seconds or 0)
    days = parse_active_days(active_days)
    if interval > 0 and has_window(window_start_min, window_end_min):
        slot = next_windowed_slot(
            now,
            interval_seconds=interval,
            window_start_min=int(window_start_min),
            window_end_min=int(window_end_min),
            active_days=days,
        )
        if slot is not None:
            return slot
    if interval == 86400:
        hinted = _clock_hint_from_message(message)
        if hinted is not None:
            return _next_at_msk_clock(hinted, now)
    origin = _as_utc(fire_at)
    if interval <= 0:
        return now
    if origin is None:
        result = now + timedelta(seconds=interval)
    elif origin > now:
        result = origin
    else:
        elapsed = (now - origin).total_seconds()
        steps = int(elapsed // interval) + 1
        result = origin + timedelta(seconds=steps * interval)
    if days:
        for _ in range(400):
            if result.astimezone(_MSK).weekday() in days:
                return result
            result = result + timedelta(seconds=interval)
    return result


def _advance_past_skipped(row: AgentTrigger, *, now: datetime) -> None:
    interval = int(row.interval_seconds or 0)
    if interval <= 0:
        if slot_is_skipped(row, row.fire_at):
            row.enabled = False
        return
    guard = 0
    while guard < 80 and slot_is_skipped(row, row.fire_at):
        row.fire_at = next_aligned_fire_at(
            row.fire_at,
            interval,
            now=_as_utc(row.fire_at) or now,
            message=row.message or "",
            active_days=getattr(row, "active_days", ""),
            window_start_min=getattr(row, "window_start_min", None),
            window_end_min=getattr(row, "window_end_min", None),
        )
        guard += 1


def _to_out(row: AgentTrigger) -> TriggerOut:
    return TriggerOut(
        id=row.id,
        owner_user_id=row.owner_user_id,
        workflow_id=row.workflow_id,
        created_by_workflow_id=row.created_by_workflow_id or "",
        message=row.message or "",
        condition_text=row.condition_text or "",
        fire_at=row.fire_at,
        interval_seconds=int(row.interval_seconds or 0),
        once=bool(row.once),
        enabled=bool(row.enabled),
        last_checked_at=row.last_checked_at,
        last_fired_at=row.last_fired_at,
        cooldown_until=row.cooldown_until,
        last_evidence=row.last_evidence or "",
        created_at=row.created_at,
        active_days=sorted(parse_active_days(getattr(row, "active_days", ""))),
        window_start=format_min_to_clock(getattr(row, "window_start_min", None)),
        window_end=format_min_to_clock(getattr(row, "window_end_min", None)),
    )


def create_trigger(db: Session, *, owner_user_id: str, payload: TriggerCreate) -> TriggerOut:
    workflow_id = (payload.workflow_id or payload.created_by_workflow_id or "").strip()
    if not workflow_id:
        raise TriggerError("Нужен workflow_id агента, которого запускать")
    workflow = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == owner_user_id)
        .first()
    )
    if workflow is None:
        raise TriggerError("Агент не найден", 404)
    condition = (payload.condition or "").strip()
    now = datetime.now(timezone.utc)
    fire_at = _as_utc(payload.at)
    interval_seconds = 0
    if payload.interval_seconds is not None:
        try:
            interval_seconds = int(float(payload.interval_seconds))
        except (TypeError, ValueError) as exc:
            raise TriggerError("interval_seconds должен быть числом") from exc
        if interval_seconds < 0:
            raise TriggerError("interval_seconds не может быть отрицательным")
    if fire_at is None and payload.after_seconds is not None:
        try:
            seconds = float(payload.after_seconds)
        except (TypeError, ValueError) as exc:
            raise TriggerError("after_seconds должен быть числом") from exc
        if seconds < 0:
            raise TriggerError("after_seconds не может быть отрицательным")
        fire_at = now + timedelta(seconds=seconds)
    active_days = format_active_days(getattr(payload, "active_days", None))
    window_start_min = parse_clock_to_min(getattr(payload, "window_start", "") or "")
    window_end_min = parse_clock_to_min(getattr(payload, "window_end", "") or "")
    windowed = interval_seconds > 0 and has_window(window_start_min, window_end_min)
    if interval_seconds > 0 and fire_at is None:
        if windowed:
            slot = next_windowed_slot(
                now,
                interval_seconds=interval_seconds,
                window_start_min=int(window_start_min),
                window_end_min=int(window_end_min),
                active_days=parse_active_days(active_days),
                inclusive=True,
            )
            fire_at = slot or now + timedelta(seconds=interval_seconds)
        else:
            fire_at = next_aligned_fire_at(
                None,
                interval_seconds,
                now=now,
                message=(payload.message or "").strip(),
                active_days=active_days,
            )
    if fire_at is None and not condition and interval_seconds <= 0:
        raise TriggerError("Укажи at, after_seconds, interval_seconds или condition")
    if fire_at is None:
        fire_at = now
    once = False if interval_seconds > 0 else bool(payload.once)
    row = AgentTrigger(
        id=str(uuid.uuid4()),
        owner_user_id=owner_user_id,
        workflow_id=workflow.id,
        created_by_workflow_id=(payload.created_by_workflow_id or "").strip(),
        message=(payload.message or "").strip(),
        condition_text=condition,
        fire_at=fire_at,
        interval_seconds=interval_seconds,
        active_days=active_days,
        window_start_min=window_start_min if windowed else None,
        window_end_min=window_end_min if windowed else None,
        skipped_slots=[],
        once=once,
        enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Trigger created id=%s workflow=%s condition=%s", row.id, row.workflow_id, bool(condition))
    _notify_board(db, user_id=owner_user_id, workflow_id=row.workflow_id, reason="scheduled")
    return _to_out(row)


def list_triggers(db: Session, *, user_id: str) -> list[TriggerOut]:
    rows = (
        db.execute(
            select(AgentTrigger)
            .where(AgentTrigger.owner_user_id == user_id, AgentTrigger.enabled.is_(True))
            .order_by(AgentTrigger.created_at.desc())
            .limit(100)
        )
        .scalars()
        .all()
    )
    return [_to_out(row) for row in rows]


def cancel_trigger(db: Session, *, user_id: str, trigger_id: str) -> TriggerOut:
    row = db.get(AgentTrigger, trigger_id)
    if row is None or row.owner_user_id != user_id:
        raise TriggerError("Триггер не найден", 404)
    row.enabled = False
    db.commit()
    db.refresh(row)
    _notify_board(db, user_id=user_id, workflow_id=row.workflow_id, reason="cancelled")
    return _to_out(row)


def skip_trigger_slot(
    db: Session,
    *,
    user_id: str,
    trigger_id: str,
    at: datetime,
) -> TriggerOut:
    """Cancel one planned slot. The rest of the schedule stays."""
    row = get_trigger(db, user_id=user_id, trigger_id=trigger_id)
    target = _as_utc(at)
    if target is None:
        raise TriggerError("Нужно время слота")
    key = slot_key(target)
    if not key:
        raise TriggerError("Нужно время слота")
    slots = list(getattr(row, "skipped_slots", None) or [])
    if key not in parse_skipped_slots(slots):
        slots.append(key)
    row.skipped_slots = slots
    flag_modified(row, "skipped_slots")
    now = datetime.now(timezone.utc)
    current = _as_utc(row.fire_at)
    same_slot = same_calendar_slot(row.fire_at, target)
    if same_slot or (current is not None and abs((current - target).total_seconds()) < 60):
        interval = int(row.interval_seconds or 0)
        if interval > 0:
            row.fire_at = next_aligned_fire_at(
                row.fire_at,
                interval,
                now=current or now,
                message=row.message or "",
                active_days=getattr(row, "active_days", ""),
                window_start_min=getattr(row, "window_start_min", None),
                window_end_min=getattr(row, "window_end_min", None),
            )
        elif row.once:
            row.enabled = False
    _advance_past_skipped(row, now=now)
    db.commit()
    db.refresh(row)
    _notify_board(db, user_id=user_id, workflow_id=row.workflow_id, reason="cancelled")
    return _to_out(row)


def consume_skipped_due(db: Session, row: AgentTrigger) -> bool:
    """Advance a due trigger whose current slot was cancelled by the user."""
    if not slot_is_skipped(row, row.fire_at):
        return False
    now = datetime.now(timezone.utc)
    interval = int(row.interval_seconds or 0)
    if interval > 0:
        row.fire_at = next_aligned_fire_at(
            row.fire_at,
            interval,
            now=_as_utc(row.fire_at) or now,
            message=row.message or "",
            active_days=getattr(row, "active_days", ""),
            window_start_min=getattr(row, "window_start_min", None),
            window_end_min=getattr(row, "window_end_min", None),
        )
    _advance_past_skipped(row, now=now)
    db.commit()
    _notify_board(db, user_id=row.owner_user_id, workflow_id=row.workflow_id, reason="cancelled")
    return True


def interval_seconds_from_spec(spec: ScheduleTriggerSpec) -> int:
    value = float(spec.interval_value or 0)
    unit = (spec.interval_unit or "hours").casefold()
    if unit == "minutes":
        return max(0, int(round(value * 60)))
    if unit == "days":
        return max(0, int(round(value * 86400)))
    return max(0, int(round(value * 3600)))


def _is_passport_trigger(row: AgentTrigger) -> bool:
    if int(row.interval_seconds or 0) > 0:
        return True
    if (row.condition_text or "").strip():
        return True
    return not bool(row.once)


def _fire_at_from_datetime_spec(spec: ScheduleTriggerSpec) -> datetime | None:
    raw = (spec.at or "").strip()
    if not raw:
        return None
    if re.fullmatch(r"\s*\d{1,2}[:.]\d{2}\s*", raw):
        minutes = parse_clock_to_min(raw)
        if minutes is None:
            return None
        return _next_at_msk_clock((minutes // 60, minutes % 60), datetime.now(timezone.utc))
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return _as_utc(parsed)


def create_trigger_from_spec(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    spec: ScheduleTriggerSpec,
) -> TriggerOut | None:
    kind = (spec.kind or "").strip().casefold()
    if kind == "interval":
        seconds = interval_seconds_from_spec(spec)
        if seconds <= 0:
            return None
        return create_trigger(
            db,
            owner_user_id=user_id,
            payload=TriggerCreate(
                workflow_id=workflow_id,
                message=spec.message or "",
                interval_seconds=seconds,
                once=False,
                active_days=list(spec.weekdays or []),
                window_start=spec.window_start or "",
                window_end=spec.window_end or "",
            ),
        )
    if kind == "event":
        condition = (spec.condition or "").strip()
        if not condition:
            return None
        return create_trigger(
            db,
            owner_user_id=user_id,
            payload=TriggerCreate(
                workflow_id=workflow_id,
                message=spec.message or "",
                condition=condition,
                once=bool(spec.once),
            ),
        )
    fire_at = _fire_at_from_datetime_spec(spec)
    if fire_at is None:
        return None
    return create_trigger(
        db,
        owner_user_id=user_id,
        payload=TriggerCreate(
            workflow_id=workflow_id,
            message=spec.message or "",
            at=fire_at,
            once=bool(spec.once),
        ),
    )


def sync_recurring_triggers_from_draft(
    db: Session,
    *,
    user_id: str,
    workflow: Workflow,
) -> None:
    """Replace passport triggers with the current schedule_draft. Keep one-shot slots."""
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    draft = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    specs: list[ScheduleTriggerSpec] = []
    for item in draft.get("triggers") or []:
        if not isinstance(item, dict):
            continue
        try:
            specs.append(ScheduleTriggerSpec.model_validate(item))
        except (TypeError, ValueError):
            continue
    rows = list(
        db.execute(
            select(AgentTrigger).where(
                AgentTrigger.owner_user_id == user_id,
                AgentTrigger.workflow_id == workflow.id,
                AgentTrigger.enabled.is_(True),
            )
        ).scalars()
    )
    disabled = False
    for row in rows:
        if _is_passport_trigger(row):
            row.enabled = False
            disabled = True
    if disabled:
        db.commit()
    for spec in specs:
        create_trigger_from_spec(db, user_id=user_id, workflow_id=workflow.id, spec=spec)


def cancel_triggers_for_workflow(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    commit: bool = True,
) -> int:
    rows = list(
        db.execute(
            select(AgentTrigger).where(
                AgentTrigger.owner_user_id == user_id,
                AgentTrigger.workflow_id == workflow_id,
                AgentTrigger.enabled.is_(True),
            )
        ).scalars()
    )
    for row in rows:
        row.enabled = False
    if commit and rows:
        db.commit()
    return len(rows)


def delete_triggers_for_workflow(db: Session, *, user_id: str, workflow_id: str) -> int:
    count = (
        db.query(AgentTrigger)
        .filter(
            AgentTrigger.owner_user_id == user_id,
            AgentTrigger.workflow_id == workflow_id,
        )
        .delete(synchronize_session=False)
    )
    return int(count or 0)


def get_trigger(db: Session, *, user_id: str, trigger_id: str) -> AgentTrigger:
    row = db.get(AgentTrigger, trigger_id)
    if row is None or row.owner_user_id != user_id:
        raise TriggerError("Триггер не найден", 404)
    return row


def workflow_has_started_run(db: Session, workflow_id: str) -> bool:
    """Same published agent cannot start another scheduled run while one is in flight."""
    wid = (workflow_id or "").strip()
    if not wid:
        return False
    return (
        db.execute(
            select(AgentRun.id)
            .where(AgentRun.workflow_id == wid, AgentRun.status == "started")
            .limit(1)
        ).scalar_one_or_none()
        is not None
    )


def due_commands(db: Session, *, user_id: str | None = None) -> list[AgentTrigger]:
    now = datetime.now(timezone.utc)
    stale_before = now - CHECK_INTERVAL
    stmt = (
        select(AgentTrigger, Workflow)
        .join(Workflow, Workflow.id == AgentTrigger.workflow_id)
        .where(
            AgentTrigger.enabled.is_(True),
            or_(AgentTrigger.fire_at.is_(None), AgentTrigger.fire_at <= now),
            or_(AgentTrigger.cooldown_until.is_(None), AgentTrigger.cooldown_until <= now),
            or_(AgentTrigger.last_checked_at.is_(None), AgentTrigger.last_checked_at <= stale_before),
        )
    )
    if user_id:
        stmt = stmt.where(AgentTrigger.owner_user_id == user_id)
    stmt = stmt.order_by(AgentTrigger.created_at.asc()).limit(50)
    due: list[AgentTrigger] = []
    for trigger, workflow in db.execute(stmt).all():
        if workflow_is_inactive(workflow):
            continue
        due.append(trigger)
    return due


def claim_due_trigger(db: Session, trigger_id: str, *, now: datetime | None = None) -> bool:
    """Atomically take a due trigger. Only one worker/tick wins."""
    now = now or datetime.now(timezone.utc)
    stale_before = now - CHECK_INTERVAL
    result = db.execute(
        update(AgentTrigger)
        .where(
            AgentTrigger.id == trigger_id,
            AgentTrigger.enabled.is_(True),
            or_(AgentTrigger.last_checked_at.is_(None), AgentTrigger.last_checked_at <= stale_before),
        )
        .values(last_checked_at=now)
        .returning(AgentTrigger.id)
    )
    claimed = result.scalar_one_or_none()
    if claimed is None:
        db.rollback()
        return False
    db.commit()
    return True


def claim_due_agent_jobs(db: Session, *, user_id: str | None = None) -> list[AgentTrigger]:
    claimed: list[AgentTrigger] = []
    for row in due_commands(db, user_id=user_id):
        if consume_skipped_due(db, row):
            continue
        if claim_due_trigger(db, row.id):
            claimed.append(row)
    return claimed


def agent_run_task_id(
    trigger_id: str,
    *,
    now: datetime | None = None,
    interval_seconds: int = 0,
    fire_at: datetime | None = None,
) -> str:
    now = now or datetime.now(timezone.utc)
    window = int(CHECK_INTERVAL.total_seconds()) or 45
    slot = int(now.timestamp() // window)
    _ = interval_seconds, fire_at
    return f"agent-run:{trigger_id}:{slot}"


def kpi_calc_task_id(workflow_id: str, tile_ids: list[str], *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    tiles = ",".join(sorted(str(item) for item in tile_ids))
    slot = int(now.timestamp() // 60)
    return f"kpi-calc:{workflow_id}:{slot}:{tiles}"


def mark_dispatched(db: Session, trigger_id: str) -> None:
    row = db.get(AgentTrigger, trigger_id)
    if row is None:
        return
    row.last_checked_at = datetime.now(timezone.utc)
    db.commit()


def mark_fired(db: Session, *, user_id: str, trigger_id: str, evidence: str = "") -> TriggerOut:
    row = get_trigger(db, user_id=user_id, trigger_id=trigger_id)
    now = datetime.now(timezone.utc)
    row.last_fired_at = now
    row.last_evidence = (evidence or "").strip()
    row.last_checked_at = now
    interval = int(row.interval_seconds or 0)
    if interval > 0:
        row.once = False
        row.enabled = True
        row.fire_at = next_aligned_fire_at(
            row.fire_at,
            interval,
            now=now,
            message=row.message or "",
            active_days=getattr(row, "active_days", ""),
            window_start_min=getattr(row, "window_start_min", None),
            window_end_min=getattr(row, "window_end_min", None),
        )
        _advance_past_skipped(row, now=now)
        row.cooldown_until = now + FIRE_COOLDOWN
    elif row.once:
        row.enabled = False
    else:
        row.cooldown_until = now + FIRE_COOLDOWN
    db.commit()
    db.refresh(row)
    return _to_out(row)


def mark_skipped(
    db: Session,
    *,
    user_id: str,
    trigger_id: str,
    evidence: str,
    retry_in_seconds: int | None = None,
    advance: bool = True,
) -> TriggerOut:
    """Defer or skip a slot. advance=False keeps fire_at so the plan stays on the calendar."""
    row = get_trigger(db, user_id=user_id, trigger_id=trigger_id)
    now = datetime.now(timezone.utc)
    row.last_checked_at = now
    row.last_evidence = (evidence or "").strip()
    if retry_in_seconds is not None and retry_in_seconds > 0:
        # Keep the clock grid. Only delay the next claim so the calendar
        # does not crawl (10:00 -> 11:04 -> 11:05) while the desktop reconnects.
        row.cooldown_until = now + timedelta(seconds=int(retry_in_seconds))
    elif advance:
        interval = int(row.interval_seconds or 0)
        if interval > 0:
            row.fire_at = next_aligned_fire_at(
                row.fire_at,
                interval,
                now=now,
                message=row.message or "",
                active_days=getattr(row, "active_days", ""),
                window_start_min=getattr(row, "window_start_min", None),
                window_end_min=getattr(row, "window_end_min", None),
            )
            row.cooldown_until = now + FIRE_COOLDOWN
        else:
            row.cooldown_until = now + timedelta(minutes=30)
    db.commit()
    db.refresh(row)
    _notify_board(db, user_id=user_id, workflow_id=row.workflow_id, reason="skipped")
    return _to_out(row)


def _notify_board(db: Session, *, user_id: str, workflow_id: str = "", reason: str = "") -> None:
    try:
        from app.services.workflows.board_live import push_board_updated

        push_board_updated(db, user_id=user_id, workflow_id=workflow_id, reason=reason)
    except Exception:  # noqa: BLE001
        logger.exception("Board live notify failed user=%s workflow=%s", user_id, workflow_id)


_GENERIC_CHANGE = {
    "",
    "запущен",
    "условие выполнено",
    "условие сработало",
    "данные обновились",
    "что-то изменилось",
    "изменилось",
    "нет условия — срабатывание по времени",
}


def describe_trigger_reason(row: AgentTrigger | None, *, evidence: str = "") -> tuple[str, str]:
    """Краткий kind и понятная причина срабатывания для истории запусков."""
    note = _clean_change_note(evidence)
    if row is not None and not note:
        note = _clean_change_note(row.last_evidence)
    condition = (row.condition_text if row is not None else "") or ""
    condition = condition.strip()
    if condition:
        if note and note.casefold() != condition.casefold():
            return "event", f"Изменилось: {note}"
        return "event", f"Сработало условие «{condition}», но что именно изменилось — не зафиксировано"
    interval = int(getattr(row, "interval_seconds", 0) or 0) if row is not None else 0
    if interval > 0:
        return "interval", f"Наступило время по расписанию ({_format_interval(interval)})"
    if row is not None:
        when = _as_utc(row.fire_at)
        if when is not None:
            stamp = when.astimezone().strftime("%d.%m.%Y %H:%M")
            return "time", f"Наступило запланированное время ({stamp})"
        return "time", "Наступило запланированное время"
    if note:
        return "event", f"Изменилось: {note}"
    return "", "Сработал триггер"


def _clean_change_note(value: object) -> str:
    note = re.sub(r"\s+", " ", str(value or "").strip())
    if not note:
        return ""
    for prefix in ("изменилось:", "что-то изменилось:", "причина:"):
        if note.casefold().startswith(prefix):
            note = note[len(prefix) :].strip()
    if note.casefold() in _GENERIC_CHANGE:
        return ""
    return note


def _format_interval(seconds: int) -> str:
    if seconds <= 0:
        return "по расписанию"
    if seconds % 86400 == 0:
        days = seconds // 86400
        if days == 1:
            return "каждый день"
        return f"каждые {days} дн."
    if seconds % 3600 == 0:
        hours = seconds // 3600
        if hours == 1:
            return "каждый час"
        return f"каждые {hours} ч."
    if seconds % 60 == 0:
        minutes = seconds // 60
        if minutes == 1:
            return "каждую минуту"
        return f"каждые {minutes} мин."
    return f"каждые {seconds} с."


def command_payload(row: AgentTrigger | TriggerOut) -> dict:
    if isinstance(row, TriggerOut):
        data = row.model_dump(mode="json")
    else:
        data = _to_out(row).model_dump(mode="json")
    if (data.get("condition_text") or "").strip():
        data["type"] = "evaluate_trigger"
        data["condition"] = data.get("condition_text") or ""
    else:
        data["type"] = "run_agent"
    data["trigger_id"] = data.get("id") or ""
    return data
