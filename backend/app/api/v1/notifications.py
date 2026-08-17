from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.jwt import AuthContext, validate_token
from app.db.session import SessionLocal, get_db
from app.schemas.notification import (
    DirectoryUserList,
    NotificationCreate,
    NotificationOut,
)
from app.services.notifications.hub import hub
from app.services.notifications.service import (
    NotificationError,
    create_notification,
    due_undelivered,
    list_directory_users,
    list_pending,
    mark_delivered,
    payload_dict,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("/users", response_model=DirectoryUserList)
def read_directory_users(
    search: str = Query(default=""),
    _: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DirectoryUserList:
    return DirectoryUserList(items=list_directory_users(db, search=search))


@router.post("", response_model=NotificationOut)
async def create_notification_endpoint(
    body: NotificationCreate,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationOut:
    try:
        item = create_notification(db, sender_user_id=auth.user_id, payload=body)
    except NotificationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    await _deliver_if_due(db, item)
    return item


@router.get("/pending", response_model=list[NotificationOut])
def read_pending(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationOut]:
    return list_pending(db, user_id=auth.user_id)


@router.post("/{notification_id}/ack")
def ack_notification(
    notification_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    from app.models.notification import Notification

    row = db.get(Notification, notification_id)
    if row is None or row.recipient_user_id != auth.user_id:
        raise HTTPException(status_code=404, detail="Уведомление не найдено")
    mark_delivered(db, notification_id)
    return {"ok": True}


@router.websocket("/ws")
async def notifications_ws(websocket: WebSocket, token: str = "") -> None:
    try:
        auth = validate_token(token)
    except ValueError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    hub.add(auth.user_id, websocket)
    db = SessionLocal()
    try:
        for item in list_pending(db, user_id=auth.user_id):
            sent = await hub.push(auth.user_id, payload_dict(item))
            if sent:
                mark_delivered(db, item.id)
        from app.api.v1.triggers import dispatch_due_triggers

        await dispatch_due_triggers(user_id=auth.user_id)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Notification websocket failed user=%s", auth.user_id)
    finally:
        hub.remove(auth.user_id, websocket)
        db.close()


async def _deliver_if_due(db: Session, item: NotificationOut) -> None:
    from datetime import datetime, timezone

    send_at = item.send_at
    if send_at.tzinfo is None:
        send_at = send_at.replace(tzinfo=timezone.utc)
    if send_at > datetime.now(timezone.utc):
        return
    sent = await hub.push(item.recipient_user_id, payload_dict(item))
    if sent:
        mark_delivered(db, item.id)


async def deliver_due_notifications() -> None:
    db = SessionLocal()
    try:
        for row in due_undelivered(db):
            sent = await hub.push(row.recipient_user_id, payload_dict(row))
            if sent:
                mark_delivered(db, row.id)
    finally:
        db.close()


async def notification_scheduler() -> None:
    while True:
        await asyncio.sleep(20)
        try:
            await deliver_due_notifications()
        except Exception:  # noqa: BLE001
            logger.exception("Notification scheduler tick failed")
