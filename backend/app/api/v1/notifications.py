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
    NotificationInbox,
    NotificationOut,
)
from app.services.notifications.hub import hub
from app.services.notifications.service import (
    NotificationError,
    clear_inbox,
    create_notification,
    due_undelivered,
    list_directory_users,
    list_inbox,
    latest_due_by_recipient,
    list_pending,
    mark_all_read,
    mark_delivered,
    split_latest,
    mark_read,
    payload_dict,
    unread_count,
)
from app.services.sessions import is_current_session, mark_online

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


@router.get("", response_model=NotificationInbox)
def read_inbox(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NotificationInbox:
    items = list_inbox(db, user_id=auth.user_id)
    return NotificationInbox(items=items, unread_count=sum(1 for item in items if item.unread))


@router.get("/unread-count")
def read_unread_count(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    mark_online(auth.user_id, auth.session_id)
    return {"count": unread_count(db, user_id=auth.user_id)}


@router.post("/read-all")
def read_all_notifications(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"updated": mark_all_read(db, user_id=auth.user_id)}


@router.post("/clear")
def clear_notifications(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    return {"deleted": clear_inbox(db, user_id=auth.user_id)}


@router.get("/pending", response_model=list[NotificationOut])
def read_pending(
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[NotificationOut]:
    # Desktop polls every ~15s; keep Redis presence alive even if WS briefly drops.
    mark_online(auth.user_id, auth.session_id)
    return list_pending(db, user_id=auth.user_id)


@router.post("/{notification_id}/read")
def read_notification(
    notification_id: str,
    auth: AuthContext = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    try:
        mark_read(db, user_id=auth.user_id, notification_id=notification_id)
    except NotificationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return {"ok": True}


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
    if not is_current_session(auth.user_id, auth.session_id):
        await websocket.close(code=4001)
        return
    await websocket.accept()
    await hub.replace(auth.user_id, websocket, session_id=auth.session_id)
    mark_online(auth.user_id, auth.session_id)
    db = SessionLocal()
    try:
        pending = list_pending(db, user_id=auth.user_id)
        older, latest = split_latest(pending)
        for item in older:
            mark_delivered(db, item.id)
        if latest is not None:
            sent = await hub.push(auth.user_id, payload_dict(latest))
            if sent:
                mark_delivered(db, latest.id)
        while True:
            await websocket.receive_text()
            if not is_current_session(auth.user_id, auth.session_id):
                await websocket.close(code=4001)
                break
            mark_online(auth.user_id, auth.session_id)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Notification websocket failed user=%s", auth.user_id)
    finally:
        hub.remove(auth.user_id, websocket)
        # Do not mark_offline on a WS blip: the desktop still polls /pending every 15s.
        # Clearing presence here made Celery skip a live app and drop the calendar slot.
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
        older, latest_rows = latest_due_by_recipient(due_undelivered(db))
        for row in older:
            mark_delivered(db, row.id)
        for row in latest_rows:
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


async def board_live_subscriber() -> None:
    from app.services.sessions import _redis
    from app.services.desktop_commands import DESKTOP_COMMAND_CHANNEL
    from app.services.workflows.board_live import BOARD_CHANNEL, relay_board_message
    from app.services.workflows.tool_live import TOOL_CHANNEL

    while True:
        client = _redis()
        if client is None:
            await asyncio.sleep(3)
            continue
        pubsub = None
        try:
            pubsub = client.pubsub()
            pubsub.subscribe(BOARD_CHANNEL, TOOL_CHANNEL, DESKTOP_COMMAND_CHANNEL)
            logger.info("Board live subscriber connected")
            while True:
                message = await asyncio.to_thread(pubsub.get_message, True, 0.4)
                if not message:
                    continue
                await relay_board_message(message.get("data"))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Board live subscriber failed")
            await asyncio.sleep(2)
        finally:
            if pubsub is not None:
                try:
                    pubsub.close()
                except Exception:  # noqa: BLE001
                    pass
