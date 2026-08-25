from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.user import AppUser
from app.modules.chat.crypto import decrypt_text
from app.modules.chat.domain.messages import add_message, mark_read, member_ids
from app.modules.chat.domain.presence import set_activity
from app.modules.chat.domain.threads import open_dm
from app.modules.chat.models import ChatSupportTicket, ChatThread
from app.modules.chat.support.tickets import (
    drain_queued,
    ensure_assigned,
    get_or_create_support_thread,
    reopen_if_closed,
)

logger = logging.getLogger(__name__)


def handle_command(db: Session, command: dict[str, Any]) -> list[dict[str, Any]]:
    kind = str(command.get("type") or "")
    user_id = str(command.get("user_id") or "")
    client_id = str(command.get("client_id") or "")
    if kind == "send_message":
        return _send(db, user_id, client_id, command)
    if kind == "mark_read":
        return _read(db, user_id, command)
    if kind == "set_activity":
        return _activity(db, user_id, command)
    if kind == "open_dm":
        return _open_dm(db, user_id, command)
    if kind == "ticket_close":
        return _ticket_status(db, user_id, command, "closed")
    if kind == "ticket_return":
        return _ticket_status(db, user_id, command, "queued")
    if kind == "ticket_assign":
        return _ticket_assign(db, user_id, command)
    if kind == "drain_queue":
        return _drain(db)
    raise ValueError(f"Неизвестная команда: {kind}")


def handle_command_and_emit(command: dict[str, Any]) -> None:
    from app.modules.chat.realtime import dispatch_event

    with SessionLocal() as db:
        events = handle_command(db, command)
        db.commit()
        for event in events:
            dispatch_event(event)


def _thread_for(db: Session, user_id: str, command: dict[str, Any]) -> ChatThread:
    thread_id = str(command.get("thread_id") or "")
    if thread_id:
        thread = db.get(ChatThread, thread_id)
        if thread is None:
            raise ValueError("Диалог не найден")
        return thread
    if str(command.get("kind") or "") == "support":
        thread, ticket = get_or_create_support_thread(db, user_id)
        reopen_if_closed(ticket)
        ensure_assigned(db, ticket)
        return thread
    peer_id = str(command.get("peer_id") or "")
    if not peer_id:
        raise ValueError("Не указан собеседник")
    return open_dm(db, user_id, peer_id)


def _send(db: Session, user_id: str, client_id: str, command: dict[str, Any]) -> list[dict[str, Any]]:
    thread = _thread_for(db, user_id, command)
    if thread.kind == "support":
        from sqlalchemy import select

        row = db.execute(
            select(ChatSupportTicket).where(ChatSupportTicket.thread_id == thread.id)
        ).scalar_one_or_none()
        if row is not None:
            reopen_if_closed(row)
            ensure_assigned(db, row)
    message = add_message(
        db,
        thread=thread,
        sender_id=user_id,
        text=str(command.get("text") or ""),
        client_id=client_id,
        file_ids=list(command.get("file_ids") or []),
    )
    events = [
        {
            "type": "chat_message",
            "user_ids": member_ids(db, thread.id),
            "thread_id": thread.id,
            "message": {
                "id": message.id,
                "thread_id": thread.id,
                "sender_id": message.sender_id,
                "text": decrypt_text(message.text or ""),
                "client_id": message.client_id,
                "created_at": message.created_at.isoformat(),
            },
        }
    ]
    return events


def _read(db: Session, user_id: str, command: dict[str, Any]) -> list[dict[str, Any]]:
    thread_id = str(command.get("thread_id") or "")
    mark_read(db, thread_id, user_id)
    return [
        {
            "type": "chat_receipt",
            "user_ids": member_ids(db, thread_id),
            "thread_id": thread_id,
            "reader_id": user_id,
            "status": "read",
        }
    ]


def _presence_audience(db: Session, user_id: str) -> list[str]:
    from sqlalchemy import select

    from app.modules.chat.models import ChatThreadMember

    thread_ids = select(ChatThreadMember.thread_id).where(ChatThreadMember.user_id == user_id)
    rows = db.execute(
        select(ChatThreadMember.user_id).where(ChatThreadMember.thread_id.in_(thread_ids))
    ).all()
    return list({str(row[0]) for row in rows} | {user_id})


def _activity(db: Session, user_id: str, command: dict[str, Any]) -> list[dict[str, Any]]:
    user = set_activity(db, user_id, str(command.get("status") or ""))
    events = [
        {
            "type": "presence",
            "user_ids": _presence_audience(db, user_id),
            "user_id": user.id,
            "activity_status": user.activity_status,
        }
    ]
    if user.activity_status != "away":
        events.extend(_drain(db))
    return events


def _open_dm(db: Session, user_id: str, command: dict[str, Any]) -> list[dict[str, Any]]:
    thread = open_dm(db, user_id, str(command.get("peer_id") or ""))
    return [{"type": "thread_opened", "user_ids": [user_id], "thread_id": thread.id, "kind": "dm"}]


def _ticket_status(db: Session, user_id: str, command: dict[str, Any], status: str) -> list[dict[str, Any]]:
    ticket = db.get(ChatSupportTicket, str(command.get("ticket_id") or ""))
    if ticket is None:
        raise ValueError("Тикет не найден")
    actor = db.get(AppUser, user_id)
    from app.modules.chat.support.assign import is_support_user

    if not is_support_user(actor, user_id):
        raise PermissionError("Нет прав поддержки")
    if status == "closed":
        ticket.status = "closed"
        ticket.closed_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    else:
        ticket.status = "queued"
        ticket.assigned_to = None
        ticket.assigned_at = None
        ticket.closed_at = None
    return [
        {
            "type": "ticket_updated",
            "user_ids": member_ids(db, ticket.thread_id),
            "ticket_id": ticket.id,
            "status": ticket.status,
            "assigned_to": ticket.assigned_to,
        }
    ]


def _ticket_assign(db: Session, user_id: str, command: dict[str, Any]) -> list[dict[str, Any]]:
    ticket = db.get(ChatSupportTicket, str(command.get("ticket_id") or ""))
    if ticket is None:
        raise ValueError("Тикет не найден")
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.modules.chat.models import ChatThreadMember
    from app.modules.chat.support.assign import is_support_user

    actor = db.get(AppUser, user_id)
    if not is_support_user(actor, user_id):
        raise PermissionError("Нет прав поддержки")
    target = str(command.get("assigned_to") or user_id)
    ticket.status = "assigned"
    ticket.assigned_to = target
    ticket.assigned_at = datetime.now(timezone.utc)
    exists = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == ticket.thread_id,
            ChatThreadMember.user_id == target,
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(ChatThreadMember(thread_id=ticket.thread_id, user_id=target, role="agent"))
    return [
        {
            "type": "ticket_updated",
            "user_ids": member_ids(db, ticket.thread_id),
            "ticket_id": ticket.id,
            "status": ticket.status,
            "assigned_to": ticket.assigned_to,
        }
    ]


def _drain(db: Session) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for ticket in drain_queued(db):
        events.append(
            {
                "type": "ticket_updated",
                "user_ids": member_ids(db, ticket.thread_id),
                "ticket_id": ticket.id,
                "status": ticket.status,
                "assigned_to": ticket.assigned_to,
            }
        )
    return events
