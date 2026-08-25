from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.chat.models import ChatSupportTicket, ChatThread, ChatThreadMember
from app.modules.chat.support.assign import pick_round_robin


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create_support_thread(db: Session, author_id: str) -> tuple[ChatThread, ChatSupportTicket]:
    ticket = db.execute(
        select(ChatSupportTicket).where(ChatSupportTicket.author_id == author_id)
    ).scalar_one_or_none()
    if ticket is not None:
        thread = db.get(ChatThread, ticket.thread_id)
        if thread is None:
            thread = ChatThread(id=ticket.thread_id, kind="support")
            db.add(thread)
        return thread, ticket
    thread = ChatThread(id=f"thr-{uuid4().hex[:16]}", kind="support")
    db.add(thread)
    db.flush()
    db.add(ChatThreadMember(thread_id=thread.id, user_id=author_id, role="user"))
    ticket = ChatSupportTicket(
        id=f"tkt-{uuid4().hex[:16]}",
        thread_id=thread.id,
        author_id=author_id,
        status="queued",
        queued_at=_now(),
    )
    db.add(ticket)
    db.flush()
    return thread, ticket


def reopen_if_closed(ticket: ChatSupportTicket) -> None:
    if ticket.status != "closed":
        return
    ticket.status = "queued"
    ticket.assigned_to = None
    ticket.assigned_at = None
    ticket.closed_at = None
    ticket.queued_at = _now()


def ensure_assigned(db: Session, ticket: ChatSupportTicket) -> None:
    if ticket.status == "closed":
        return
    if ticket.status == "assigned" and ticket.assigned_to:
        return
    agent_id = pick_round_robin(db)
    if agent_id is None:
        ticket.status = "queued"
        return
    ticket.status = "assigned"
    ticket.assigned_to = agent_id
    ticket.assigned_at = _now()
    exists = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == ticket.thread_id,
            ChatThreadMember.user_id == agent_id,
        )
    ).scalar_one_or_none()
    if exists is None:
        db.add(ChatThreadMember(thread_id=ticket.thread_id, user_id=agent_id, role="agent"))


def drain_queued(db: Session) -> list[ChatSupportTicket]:
    rows = db.execute(
        select(ChatSupportTicket).where(ChatSupportTicket.status == "queued")
    ).scalars().all()
    changed: list[ChatSupportTicket] = []
    for ticket in rows:
        before = ticket.assigned_to
        ensure_assigned(db, ticket)
        if ticket.assigned_to and ticket.assigned_to != before:
            changed.append(ticket)
    return changed
