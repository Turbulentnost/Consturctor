from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.chat.models import ChatThread, ChatThreadMember


def open_dm(db: Session, user_id: str, peer_id: str) -> ChatThread:
    if user_id == peer_id:
        raise ValueError("Нельзя открыть чат с собой")
    mine = select(ChatThreadMember.thread_id).where(ChatThreadMember.user_id == user_id)
    peer = select(ChatThreadMember.thread_id).where(ChatThreadMember.user_id == peer_id)
    thread = db.execute(
        select(ChatThread).where(
            ChatThread.kind == "dm",
            ChatThread.id.in_(mine),
            ChatThread.id.in_(peer),
        )
    ).scalars().first()
    if thread is not None:
        return thread
    thread = ChatThread(id=f"thr-{uuid4().hex[:16]}", kind="dm")
    db.add(thread)
    db.flush()
    db.add(ChatThreadMember(thread_id=thread.id, user_id=user_id, role="user"))
    db.add(ChatThreadMember(thread_id=thread.id, user_id=peer_id, role="user"))
    db.flush()
    return thread
