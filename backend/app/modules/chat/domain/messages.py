from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.chat.crypto import encrypt_text
from app.modules.chat.domain.files import take_staging
from app.modules.chat.models import ChatAttachment, ChatMessage, ChatThread, ChatThreadMember


def _now() -> datetime:
    return datetime.now(timezone.utc)


def existing_by_client(db: Session, client_id: str) -> ChatMessage | None:
    if not client_id:
        return None
    return db.execute(
        select(ChatMessage).where(ChatMessage.client_id == client_id)
    ).scalar_one_or_none()


def add_message(
    db: Session,
    *,
    thread: ChatThread,
    sender_id: str,
    text: str,
    client_id: str,
    file_ids: list[str] | None = None,
) -> ChatMessage:
    found = existing_by_client(db, client_id)
    if found is not None:
        return found
    member = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == thread.id,
            ChatThreadMember.user_id == sender_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise PermissionError("Нет доступа к диалогу")
    message = ChatMessage(
        id=f"msg-{uuid4().hex[:16]}",
        thread_id=thread.id,
        sender_id=sender_id,
        text=encrypt_text((text or "").strip()),
        client_id=client_id,
        created_at=_now(),
    )
    db.add(message)
    thread.last_message_at = message.created_at
    db.flush()
    for file_id in file_ids or []:
        stored = take_staging(sender_id, file_id, message.id)
        if stored is None:
            continue
        db.add(
            ChatAttachment(
                id=stored["id"],
                message_id=message.id,
                filename=stored["filename"],
                mime=stored["mime"],
                size=stored["size"],
                storage_path=stored["storage_path"],
            )
        )
    member.last_read_at = message.created_at
    return message


def mark_read(db: Session, thread_id: str, user_id: str) -> ChatThreadMember:
    member = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == thread_id,
            ChatThreadMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise PermissionError("Нет доступа к диалогу")
    member.last_read_at = _now()
    return member


def member_ids(db: Session, thread_id: str) -> list[str]:
    rows = db.execute(
        select(ChatThreadMember.user_id).where(ChatThreadMember.thread_id == thread_id)
    ).all()
    return [str(row[0]) for row in rows]


def receipt_for(db: Session, message: ChatMessage, viewer_id: str) -> str:
    if message.sender_id != viewer_id:
        return "received"
    others = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == message.thread_id,
            ChatThreadMember.user_id != message.sender_id,
        )
    ).scalars().all()
    if not others:
        return "delivered"
    created = message.created_at
    if any(m.last_read_at is not None and m.last_read_at >= created for m in others):
        return "read"
    return "delivered"
