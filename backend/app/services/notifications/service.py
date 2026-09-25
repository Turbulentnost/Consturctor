from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.notification import Notification
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.schemas.notification import DirectoryUser, NotificationCreate, NotificationOut
from app.services.notifications.hub import hub
from app.services.triggers.service import workflow_is_deleted

logger = logging.getLogger(__name__)


class NotificationError(RuntimeError):
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


def _to_out(row: Notification, *, sender_fio: str = "") -> NotificationOut:
    return NotificationOut(
        id=row.id,
        sender_user_id=row.sender_user_id,
        recipient_user_id=row.recipient_user_id,
        title=row.title,
        body=row.body or "",
        workflow_id=row.workflow_id or "",
        run_id=row.run_id or "",
        send_at=row.send_at,
        delivered_at=row.delivered_at,
        read_at=row.read_at,
        created_at=row.created_at,
        sender_fio=sender_fio,
        unread=row.read_at is None,
    )


def list_directory_users(db: Session, *, search: str = "") -> list[DirectoryUser]:
    stmt = select(AppUser).order_by(AppUser.fio)
    needle = (search or "").strip()
    if needle:
        like = f"%{needle}%"
        stmt = stmt.where(
            or_(
                AppUser.fio.ilike(like),
                AppUser.position.ilike(like),
                AppUser.department.ilike(like),
                AppUser.id.ilike(like),
            )
        )
    rows = db.execute(stmt.limit(200)).scalars().all()
    return [
        DirectoryUser(
            id=row.id,
            fio=row.fio or "",
            position=row.position or "",
            department=row.department or "",
        )
        for row in rows
    ]


def resolve_directory_user(db: Session, value: str) -> AppUser | None:
    raw = (value or "").strip()
    if not raw:
        return None
    found = db.get(AppUser, raw)
    if found is not None:
        return found
    like = f"%{raw}%"
    return db.execute(
        select(AppUser)
        .where(
            or_(
                AppUser.fio.ilike(like),
                AppUser.id.ilike(like),
                AppUser.position.ilike(like),
            )
        )
        .order_by(AppUser.fio)
        .limit(1)
    ).scalar_one_or_none()


def create_notification(
    db: Session,
    *,
    sender_user_id: str,
    payload: NotificationCreate,
) -> NotificationOut:
    recipient = resolve_directory_user(db, payload.recipient_user_id)
    if recipient is None:
        raise NotificationError("Получатель не найден среди пользователей Constructor", 404)
    now = datetime.now(timezone.utc)
    send_at = _as_utc(payload.send_at) or now
    title = payload.title.strip()
    run_id = (payload.run_id or "").strip()
    from app.services.sessions import FINISH_RUN_TITLE, START_RUN_TITLE

    if run_id and title in {START_RUN_TITLE, FINISH_RUN_TITLE, "Начат плановый запуск"}:
        existing = db.execute(
            select(Notification).where(
                Notification.recipient_user_id == recipient.id,
                Notification.run_id == run_id,
                Notification.title == title,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _to_out(existing)
    row = Notification(
        id=str(uuid.uuid4()),
        sender_user_id=sender_user_id,
        recipient_user_id=recipient.id,
        title=payload.title.strip(),
        body=(payload.body or "").strip(),
        workflow_id=(payload.workflow_id or "").strip(),
        run_id=(payload.run_id or "").strip(),
        send_at=send_at,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    if send_at <= now:
        _try_mark_and_note(db, row)
    return _to_out(row)


def split_latest(items: list) -> tuple[list, object | None]:
    """Keep only the newest item from a backlog ordered oldest-first."""
    if not items:
        return [], None
    return list(items[:-1]), items[-1]


def _notification_title(item: object) -> str:
    return str(getattr(item, "title", "") or "").strip()


def is_run_inbox_title(title: str) -> bool:
    from app.services.sessions import (
        FINISH_RUN_TITLE,
        SKIP_RUN_TITLE,
        START_RUN_TITLE,
        WAIT_CONFIRM_TITLE,
    )

    text = (title or "").strip()
    return (
        text.startswith(START_RUN_TITLE)
        or text.startswith(FINISH_RUN_TITLE)
        or text.startswith(WAIT_CONFIRM_TITLE)
        or text == SKIP_RUN_TITLE
        or text == "Начат плановый запуск"
    )


def partition_pending(items: list) -> tuple[list, list]:
    """Split a backlog into (silent_ack, must_deliver).

    Ordinary notices still collapse to the latest one so a reconnect does not
    dump the whole inbox. Start / finish / wait for an agent run are never
    dropped — Orchestrator must show each of them.
    """
    keep: list = []
    rest: list = []
    for item in items:
        if is_run_inbox_title(_notification_title(item)):
            keep.append(item)
        else:
            rest.append(item)
    older, latest = split_latest(rest)
    deliver = list(keep)
    if latest is not None:
        deliver.append(latest)
    return older, deliver


def latest_due_by_recipient(rows: list[Notification]) -> tuple[list[Notification], list[Notification]]:
    """Return (older, deliver) for a due-undelivered backlog."""
    by_user: dict[str, list[Notification]] = {}
    for row in rows:
        by_user.setdefault(row.recipient_user_id, []).append(row)
    older: list[Notification] = []
    deliver: list[Notification] = []
    for group in by_user.values():
        drop, keep = partition_pending(group)
        older.extend(drop)
        deliver.extend(keep)
    return older, deliver


def list_pending(db: Session, *, user_id: str) -> list[NotificationOut]:
    now = datetime.now(timezone.utc)
    rows = (
        db.execute(
            select(Notification)
            .where(
                Notification.recipient_user_id == user_id,
                Notification.delivered_at.is_(None),
                Notification.send_at <= now,
            )
            .order_by(Notification.send_at.asc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return [_to_out(row) for row in rows]


def list_inbox(db: Session, *, user_id: str, limit: int = 80) -> list[NotificationOut]:
    now = datetime.now(timezone.utc)
    rows = (
        db.execute(
            select(Notification)
            .where(
                Notification.recipient_user_id == user_id,
                Notification.send_at <= now,
            )
            .order_by(Notification.created_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    sender_ids = {row.sender_user_id for row in rows}
    senders = {
        item.id: (item.fio or "")
        for item in db.execute(select(AppUser).where(AppUser.id.in_(sender_ids))).scalars().all()
    } if sender_ids else {}
    linked_ids = {str(row.workflow_id) for row in rows if (row.workflow_id or "").strip()}
    alive_rows = (
        db.query(Workflow).filter(Workflow.id.in_(linked_ids)).all() if linked_ids else []
    )
    alive_ids = {
        str(item.id)
        for item in alive_rows
        if not workflow_is_deleted(item)
    }
    items: list[NotificationOut] = []
    for row in rows:
        item = _to_out(row, sender_fio=senders.get(row.sender_user_id, ""))
        linked = (item.workflow_id or "").strip()
        if linked and linked not in alive_ids:
            item = item.model_copy(update={"workflow_id": "", "agent_deleted": True})
        items.append(item)
    return items


def delete_notifications_for_workflow(db: Session, *, workflow_id: str) -> int:
    wid = (workflow_id or "").strip()
    if not wid:
        return 0
    count = (
        db.query(Notification)
        .filter(Notification.workflow_id == wid)
        .delete(synchronize_session=False)
    )
    return int(count or 0)


def unread_count(db: Session, *, user_id: str) -> int:
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(Notification.id).where(
            Notification.recipient_user_id == user_id,
            Notification.send_at <= now,
            Notification.read_at.is_(None),
        )
    ).all()
    return len(rows)


def mark_read(db: Session, *, user_id: str, notification_id: str) -> None:
    row = db.get(Notification, notification_id)
    if row is None or row.recipient_user_id != user_id:
        raise NotificationError("Уведомление не найдено", 404)
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.commit()


def delete_notification(db: Session, *, user_id: str, notification_id: str) -> None:
    row = db.get(Notification, notification_id)
    if row is None or row.recipient_user_id != user_id:
        raise NotificationError("Уведомление не найдено", 404)
    db.delete(row)
    db.commit()


def clear_inbox(db: Session, *, user_id: str) -> int:
    count = (
        db.query(Notification)
        .filter(Notification.recipient_user_id == user_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(count or 0)


def mark_all_read(db: Session, *, user_id: str) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        db.execute(
            select(Notification).where(
                Notification.recipient_user_id == user_id,
                Notification.read_at.is_(None),
                Notification.send_at <= now,
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.read_at = now
    if rows:
        db.commit()
    return len(rows)


def mark_delivered(db: Session, notification_id: str) -> None:
    row = db.get(Notification, notification_id)
    if row is None or row.delivered_at is not None:
        return
    row.delivered_at = datetime.now(timezone.utc)
    db.commit()


def due_undelivered(db: Session) -> list[Notification]:
    now = datetime.now(timezone.utc)
    return list(
        db.execute(
            select(Notification)
            .where(
                Notification.delivered_at.is_(None),
                Notification.send_at <= now,
            )
            .order_by(Notification.send_at.asc())
            .limit(100)
        )
        .scalars()
        .all()
    )


def payload_dict(row: Notification | NotificationOut) -> dict:
    if isinstance(row, NotificationOut):
        data = row.model_dump(mode="json")
    else:
        data = _to_out(row).model_dump(mode="json")
    data["type"] = "notification"
    return data


def _try_mark_and_note(db: Session, row: Notification) -> None:
    if hub.is_online(row.recipient_user_id):
        logger.info("Notification %s queued for online user %s", row.id, row.recipient_user_id)
