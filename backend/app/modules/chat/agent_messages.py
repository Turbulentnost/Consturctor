"""Personal chat messages that an agent sends on behalf of its owner."""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.user import AppUser

AGENT_PREFIX = "[ИИ-агент]"


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("ё", "е").replace("Ё", "Е")).strip().casefold()


def _short(fio: str) -> str:
    """«Иванов Иван Иванович» -> «иванов и.и.»."""
    parts = _norm(fio).replace(".", " ").split()
    if not parts:
        return ""
    return parts[0] + " " + "".join(f"{part[0]}." for part in parts[1:3])


def resolve_recipient(query: str) -> tuple[AppUser | None, list[str]]:
    """(user, candidates). candidates is filled only when the name is ambiguous."""
    raw = (query or "").strip()
    if not raw:
        return None, []
    with SessionLocal() as db:
        found = db.get(AppUser, raw)
        if found is not None:
            return found, []
        users = [row for row in db.execute(select(AppUser)).scalars().all() if (row.fio or "").strip()]
    wanted = _norm(raw)
    exact = [row for row in users if _norm(row.fio) == wanted]
    if len(exact) == 1:
        return exact[0], []
    short = _short(raw)
    by_initials = [row for row in users if short and _short(row.fio) == short]
    if len(by_initials) == 1:
        return by_initials[0], []
    words = wanted.replace(".", " ").split()
    partial = [row for row in users if words and all(word in _norm(row.fio) for word in words)]
    if len(partial) == 1:
        return partial[0], []
    pool = exact or by_initials or partial
    return None, [row.fio for row in pool[:10]]


def send_direct_message(sender_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from app.modules.chat.bus.producer import enqueue_command

    if not sender_id:
        raise RuntimeError("Нет пользователя сессии для chat.send_direct")
    query = str(arguments.get("user_id") or arguments.get("fio") or arguments.get("recipient") or "").strip()
    text = str(arguments.get("text") or arguments.get("body") or "").strip()
    if not query or not text:
        raise RuntimeError("Для chat.send_direct нужны получатель (user_id или fio) и text")
    user, candidates = resolve_recipient(query)
    if user is None:
        note = (
            f"«{query}» совпадает с несколькими пользователями: {', '.join(candidates)}. Уточни ФИО."
            if candidates
            else f"«{query}» не найден среди пользователей Constructor — сообщение не отправлено."
        )
        return {"ok": False, "sent": False, "recipient": query, "note": note, "candidates": candidates}
    if user.id == sender_id:
        return {
            "ok": False,
            "sent": False,
            "recipient_user_id": user.id,
            "recipient_fio": user.fio,
            "note": "Получатель — владелец агента: личное сообщение самому себе не отправляется.",
        }
    client_id = uuid.uuid4().hex
    enqueue_command(
        {
            "type": "send_message",
            "user_id": sender_id,
            "peer_id": user.id,
            "client_id": client_id,
            "text": f"{AGENT_PREFIX} {text}",
        }
    )
    return {
        "ok": True,
        "sent": True,
        "recipient_user_id": user.id,
        "recipient_fio": user.fio,
        "client_id": client_id,
    }
