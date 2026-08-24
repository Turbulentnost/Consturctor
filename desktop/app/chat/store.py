from __future__ import annotations

import json
import os
from pathlib import Path

from app.chat.crypto import decrypt_text, encrypt_text
from app.chat.models import ChatAttachment, ChatMessage, ChatThread


def history_path(user_id: str) -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "turbobot" / "chat"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "_" for ch in (user_id or "local")) or "local"
    return root / f"{safe}.json"


def _read_payload(user_id: str) -> dict:
    path = history_path(user_id)
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(decrypt_text(raw) if raw.startswith("enc:v1:") else raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_history(user_id: str) -> dict[str, list[ChatMessage]]:
    threads = _read_payload(user_id).get("threads")
    if not isinstance(threads, dict):
        return {}
    result: dict[str, list[ChatMessage]] = {}
    for thread_id, rows in threads.items():
        if not isinstance(rows, list):
            continue
        result[str(thread_id)] = [_message(item) for item in rows if isinstance(item, dict)]
    return result


def load_dialogs(user_id: str) -> list[ChatThread]:
    rows = _read_payload(user_id).get("dialogs")
    if not isinstance(rows, list):
        return []
    dialogs: list[ChatThread] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        thread_id = str(item.get("id") or "")
        if not thread_id:
            continue
        dialogs.append(
            ChatThread(
                id=thread_id,
                kind=str(item.get("kind") or "dm"),
                title=str(item.get("title") or "Диалог"),
                position=str(item.get("position") or ""),
                preview=str(item.get("preview") or ""),
                last_message_at=str(item.get("last_message_at") or ""),
                unread=int(item.get("unread") or 0),
                last_read_id=str(item.get("last_read_id") or ""),
                pinned=bool(item.get("pinned")),
                peer_id=str(item.get("peer_id") or ""),
                department=str(item.get("department") or ""),
            )
        )
    return dialogs


def save_history(
    user_id: str,
    local: dict[str, list[ChatMessage]],
    dialogs: list[ChatThread] | None = None,
) -> None:
    payload = _read_payload(user_id)
    payload["threads"] = {
        thread_id: [_dump(message) for message in rows]
        for thread_id, rows in local.items()
    }
    if dialogs is not None:
        payload["dialogs"] = [
            {
                "id": item.id,
                "kind": item.kind,
                "title": item.title,
                "position": item.position,
                "preview": item.preview,
                "last_message_at": item.last_message_at,
                "unread": item.unread,
                "last_read_id": item.last_read_id,
                "pinned": item.pinned,
                "peer_id": item.peer_id,
                "department": item.department,
            }
            for item in dialogs
            if item.id and item.id != "support"
        ]
    text = json.dumps(payload, ensure_ascii=False)
    history_path(user_id).write_text(encrypt_text(text), encoding="utf-8")


def _dump(message: ChatMessage) -> dict:
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "sender_id": message.sender_id,
        "mine": message.mine,
        "text": message.text,
        "client_id": message.client_id,
        "created_at": message.created_at,
        "receipt": message.receipt,
        "attachments": [
            {
                "id": item.id,
                "filename": item.filename,
                "mime": item.mime,
                "size": item.size,
            }
            for item in message.attachments
        ],
        "agent": message.agent,
    }


def _message(item: dict) -> ChatMessage:
    files = [
        ChatAttachment(
            id=str(row.get("id") or ""),
            filename=str(row.get("filename") or ""),
            mime=str(row.get("mime") or ""),
            size=int(row.get("size") or 0),
        )
        for row in item.get("attachments") or []
        if isinstance(row, dict)
    ]
    return ChatMessage(
        id=str(item.get("id") or ""),
        thread_id=str(item.get("thread_id") or ""),
        sender_id=str(item.get("sender_id") or ""),
        mine=bool(item.get("mine")),
        text=str(item.get("text") or ""),
        client_id=str(item.get("client_id") or ""),
        created_at=str(item.get("created_at") or ""),
        receipt=("delivered" if str(item.get("receipt") or "") == "sending" else str(item.get("receipt") or "delivered")),
        attachments=files,
        agent=item.get("agent") if isinstance(item.get("agent"), dict) else None,
    )
