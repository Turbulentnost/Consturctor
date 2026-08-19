from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.trigger import AgentTrigger
from app.models.workflow import Workflow
from app.schemas.trigger import TriggerCreate, TriggerOut

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


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    if interval_seconds > 0 and fire_at is None:
        fire_at = now + timedelta(seconds=interval_seconds)
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
        once=once,
        enabled=True,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Trigger created id=%s workflow=%s condition=%s", row.id, row.workflow_id, bool(condition))
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
    return _to_out(row)


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
        if is_workflow_paused(workflow.local_run):
            continue
        due.append(trigger)
    return due


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
        row.fire_at = now + timedelta(seconds=interval)
        row.cooldown_until = now + FIRE_COOLDOWN
    elif row.once:
        row.enabled = False
    else:
        row.cooldown_until = now + FIRE_COOLDOWN
    db.commit()
    db.refresh(row)
    return _to_out(row)


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
