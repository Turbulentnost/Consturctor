from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.user import AppUser
from app.modules.chat.crypto import decrypt_text
from app.modules.chat.domain.messages import receipt_for
from app.modules.chat.models import (
    ChatAttachment,
    ChatMessage,
    ChatSupportTicket,
    ChatThread,
    ChatThreadMember,
)
from app.modules.chat.support.assign import is_support_user
from app.services.sessions import is_user_online


def _user_map(db: Session, ids: list[str]) -> dict[str, AppUser]:
    if not ids:
        return {}
    rows = db.execute(select(AppUser).where(AppUser.id.in_(ids))).scalars().all()
    return {row.id: row for row in rows}


def _preview(db: Session, thread_id: str) -> str:
    row = db.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return ""
    return decrypt_text(row.text or "").strip()


def _unread(db: Session, thread_id: str, user_id: str) -> int:
    member = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == thread_id,
            ChatThreadMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    stmt = select(ChatMessage).where(
        ChatMessage.thread_id == thread_id,
        ChatMessage.sender_id != user_id,
    )
    if member and member.last_read_at is not None:
        stmt = stmt.where(ChatMessage.created_at > member.last_read_at)
    return len(db.execute(stmt).scalars().all())


def list_threads(db: Session, user_id: str, search: str = "") -> list[dict]:
    member_threads = select(ChatThreadMember.thread_id).where(ChatThreadMember.user_id == user_id)
    threads = db.execute(
        select(ChatThread)
        .where(ChatThread.id.in_(member_threads))
        .order_by(ChatThread.last_message_at.desc().nullslast(), ChatThread.created_at.desc())
    ).scalars().all()
    items: list[dict] = []
    needle = (search or "").strip().casefold()
    for thread in threads:
        members = db.execute(
            select(ChatThreadMember).where(ChatThreadMember.thread_id == thread.id)
        ).scalars().all()
        peer_ids = [m.user_id for m in members if m.user_id != user_id]
        users = _user_map(db, peer_ids)
        title = "Поддержка" if thread.kind == "support" else ""
        position = ""
        peer_id = peer_ids[0] if peer_ids else ""
        if thread.kind == "dm" and peer_id in users:
            title = users[peer_id].fio or peer_id
            position = users[peer_id].position or ""
        preview = _preview(db, thread.id)
        hay = " ".join([title, position, preview]).casefold()
        if needle and needle not in hay:
            continue
        ticket = None
        if thread.kind == "support":
            ticket = db.execute(
                select(ChatSupportTicket).where(ChatSupportTicket.thread_id == thread.id)
            ).scalar_one_or_none()
        peer = users.get(peer_id)
        items.append(
            {
                "id": thread.id,
                "kind": thread.kind,
                "title": title or "Диалог",
                "position": position,
                "preview": preview,
                "last_message_at": thread.last_message_at.isoformat() if thread.last_message_at else None,
                "unread": _unread(db, thread.id, user_id),
                "pinned": thread.kind == "support",
                "peer_id": peer_id,
                "activity_status": getattr(peer, "activity_status", "online") if peer else "",
                "online": is_user_online(peer_id) if peer_id else False,
                "ticket_status": ticket.status if ticket else "",
                "assigned_to": ticket.assigned_to if ticket else None,
            }
        )
    items.sort(key=lambda row: (0 if row["pinned"] else 1, row["last_message_at"] or ""), reverse=False)
    dms = [row for row in items if not row["pinned"]]
    pins = [row for row in items if row["pinned"]]
    dms.sort(key=lambda row: row["last_message_at"] or "", reverse=True)
    actor = db.get(AppUser, user_id)
    if not pins and not is_support_user(actor, user_id):
        pins.append(
            {
                "id": "support",
                "kind": "support",
                "title": "Поддержка",
                "position": "",
                "preview": "",
                "last_message_at": None,
                "unread": 0,
                "pinned": True,
                "peer_id": "",
                "activity_status": "",
                "online": False,
                "ticket_status": "",
                "assigned_to": None,
            }
        )
    return pins + dms


def list_messages(db: Session, user_id: str, thread_id: str) -> list[dict]:
    member = db.execute(
        select(ChatThreadMember).where(
            ChatThreadMember.thread_id == thread_id,
            ChatThreadMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if member is None:
        raise PermissionError("Нет доступа к диалогу")
    rows = db.execute(
        select(ChatMessage)
        .where(ChatMessage.thread_id == thread_id)
        .order_by(ChatMessage.created_at.asc())
    ).scalars().all()
    result = []
    for row in rows:
        files = db.execute(
            select(ChatAttachment).where(ChatAttachment.message_id == row.id)
        ).scalars().all()
        result.append(
            {
                "id": row.id,
                "thread_id": row.thread_id,
                "sender_id": row.sender_id,
                "mine": row.sender_id == user_id,
                "text": decrypt_text(row.text or ""),
                "client_id": row.client_id,
                "created_at": row.created_at.isoformat(),
                "receipt": receipt_for(db, row, user_id),
                "attachments": [
                    {
                        "id": item.id,
                        "filename": item.filename,
                        "mime": item.mime,
                        "size": item.size,
                    }
                    for item in files
                ],
            }
        )
    return result


def list_directory(db: Session, search: str = "") -> list[dict]:
    from app.services.notifications.service import list_directory_users

    items = []
    for user in list_directory_users(db, search=search):
        row = db.get(AppUser, user.id)
        items.append(
            {
                "id": user.id,
                "fio": user.fio,
                "position": user.position,
                "department": user.department,
                "activity_status": getattr(row, "activity_status", "online") if row else "online",
                "online": is_user_online(user.id),
                "is_support": is_support_user(row, user.id),
            }
        )
    return items


def list_support_tickets(db: Session, user_id: str, shelf: str) -> list[dict]:
    actor = db.get(AppUser, user_id)
    if not is_support_user(actor, user_id):
        raise PermissionError("Нет прав поддержки")
    stmt = select(ChatSupportTicket)
    if shelf == "queue":
        stmt = stmt.where(ChatSupportTicket.status == "queued")
    elif shelf == "mine":
        stmt = stmt.where(ChatSupportTicket.assigned_to == user_id, ChatSupportTicket.status == "assigned")
    else:
        stmt = stmt.where(ChatSupportTicket.status != "closed")
    rows = db.execute(stmt.order_by(ChatSupportTicket.queued_at.asc())).scalars().all()
    authors = _user_map(db, [row.author_id for row in rows])
    result = []
    for row in rows:
        author = authors.get(row.author_id)
        result.append(
            {
                "id": row.id,
                "thread_id": row.thread_id,
                "status": row.status,
                "assigned_to": row.assigned_to,
                "author_id": row.author_id,
                "author_fio": author.fio if author else row.author_id,
                "author_position": author.position if author else "",
                "preview": _preview(db, row.thread_id),
                "queued_at": row.queued_at.isoformat() if row.queued_at else None,
            }
        )
    return result
