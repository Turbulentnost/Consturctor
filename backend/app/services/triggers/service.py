from __future__ import annotations

import logging
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
    if fire_at is None and payload.after_seconds is not None:
        try:
            seconds = float(payload.after_seconds)
        except (TypeError, ValueError) as exc:
            raise TriggerError("after_seconds должен быть числом") from exc
        if seconds < 0:
            raise TriggerError("after_seconds не может быть отрицательным")
        fire_at = now + timedelta(seconds=seconds)
    if fire_at is None and not condition:
        raise TriggerError("Укажи at, after_seconds или condition")
    if fire_at is None:
        fire_at = now
    row = AgentTrigger(
        id=str(uuid.uuid4()),
        owner_user_id=owner_user_id,
        workflow_id=workflow.id,
        created_by_workflow_id=(payload.created_by_workflow_id or "").strip(),
        message=(payload.message or "").strip(),
        condition_text=condition,
        fire_at=fire_at,
        once=bool(payload.once),
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


def get_trigger(db: Session, *, user_id: str, trigger_id: str) -> AgentTrigger:
    row = db.get(AgentTrigger, trigger_id)
    if row is None or row.owner_user_id != user_id:
        raise TriggerError("Триггер не найден", 404)
    return row


def due_commands(db: Session, *, user_id: str | None = None) -> list[AgentTrigger]:
    now = datetime.now(timezone.utc)
    stale_before = now - CHECK_INTERVAL
    stmt = select(AgentTrigger).where(
        AgentTrigger.enabled.is_(True),
        or_(AgentTrigger.fire_at.is_(None), AgentTrigger.fire_at <= now),
        or_(AgentTrigger.cooldown_until.is_(None), AgentTrigger.cooldown_until <= now),
        or_(AgentTrigger.last_checked_at.is_(None), AgentTrigger.last_checked_at <= stale_before),
    )
    if user_id:
        stmt = stmt.where(AgentTrigger.owner_user_id == user_id)
    stmt = stmt.order_by(AgentTrigger.created_at.asc()).limit(50)
    return list(db.execute(stmt).scalars().all())


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
    if row.once:
        row.enabled = False
    else:
        row.cooldown_until = now + FIRE_COOLDOWN
    db.commit()
    db.refresh(row)
    return _to_out(row)


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
