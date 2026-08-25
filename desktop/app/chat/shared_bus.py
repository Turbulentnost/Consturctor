from __future__ import annotations

import json
import os
from pathlib import Path

from app.chat.crypto import decrypt_text, encrypt_text
from app.chat.models import ChatAttachment, ChatMessage, DirectoryUser
from app.chat.store import _dump, _message


def _root() -> Path:
    path = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "turbobot" / "chat" / "shared"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pair_key(left: str, right: str) -> str:
    first, second = sorted((left or "", right or ""))
    safe = "".join(ch if ch.isalnum() else "_" for ch in f"{first}_{second}")
    return safe or "dm"


def shared_path(left: str, right: str) -> Path:
    return _root() / f"{_pair_key(left, right)}.json"


def roster_path() -> Path:
    return _root() / "roster.json"


def roster_upsert(user_id: str, fio: str, position: str = "") -> None:
    if not user_id or not fio:
        return
    rows = roster_list("")
    kept = [item for item in rows if item.id != user_id]
    kept.append(DirectoryUser(id=user_id, fio=fio, position=position, online=True))
    payload = [
        {"id": item.id, "fio": item.fio, "position": item.position}
        for item in kept
    ]
    roster_path().write_text(
        encrypt_text(json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8",
    )


def roster_list(except_id: str = "") -> list[DirectoryUser]:
    path = roster_path()
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(decrypt_text(raw) if raw.startswith("enc:v1:") else raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    users: list[DirectoryUser] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        user_id = str(item.get("id") or "")
        fio = str(item.get("fio") or "")
        if not user_id or not fio or user_id == except_id:
            continue
        users.append(
            DirectoryUser(
                id=user_id,
                fio=fio,
                position=str(item.get("position") or ""),
                online=True,
            )
        )
    return users


def load_shared(my_id: str, peer_id: str) -> list[ChatMessage]:
    path = shared_path(my_id, peer_id)
    if not path.is_file():
        return []
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(decrypt_text(raw) if raw.startswith("enc:v1:") else raw)
    except Exception:
        return []
    rows = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return []
    messages: list[ChatMessage] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        message = _message(item)
        message.thread_id = peer_id
        message.mine = message.sender_id == my_id
        if message.mine and message.receipt == "sending":
            message.receipt = "delivered"
        messages.append(message)
    return messages


def append_shared(my_id: str, peer_id: str, message: ChatMessage) -> None:
    rows = load_shared(my_id, peer_id)
    if any(item.client_id and item.client_id == message.client_id for item in rows):
        return
    payload = {
        "messages": [_dump(item) for item in rows]
        + [
            _dump(
                ChatMessage(
                    id=message.id,
                    thread_id=peer_id,
                    sender_id=my_id,
                    mine=True,
                    text=message.text,
                    client_id=message.client_id,
                    created_at=message.created_at,
                    receipt=message.receipt,
                    attachments=[
                        ChatAttachment(
                            id=item.id,
                            filename=item.filename,
                            mime=item.mime,
                            size=item.size,
                        )
                        for item in message.attachments
                    ],
                    agent=message.agent,
                )
            )
        ]
    }
    shared_path(my_id, peer_id).write_text(
        encrypt_text(json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8",
    )
