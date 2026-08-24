from __future__ import annotations

import json
import os
from pathlib import Path

from app.chat.crypto import decrypt_text, encrypt_text
from app.chat.models import ChatAttachment, ChatMessage


def history_path(user_id: str) -> Path:
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "turbobot" / "chat"
    root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() else "_" for ch in (user_id or "local")) or "local"
    return root / f"{safe}.json"


def load_history(user_id: str) -> dict[str, list[ChatMessage]]:
    path = history_path(user_id)
    if not path.is_file():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(decrypt_text(raw) if raw.startswith("enc:v1:") else raw)
    except Exception:
        return {}
    threads = payload.get("threads") if isinstance(payload, dict) else None
    if not isinstance(threads, dict):
        return {}
    result: dict[str, list[ChatMessage]] = {}
    for thread_id, rows in threads.items():
        if not isinstance(rows, list):
            continue
        result[str(thread_id)] = [_message(item) for item in rows if isinstance(item, dict)]
    return result


def save_history(user_id: str, local: dict[str, list[ChatMessage]]) -> None:
    payload = {
        "threads": {
            thread_id: [_dump(message) for message in rows]
            for thread_id, rows in local.items()
        }
    }
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
        receipt=str(item.get("receipt") or "delivered"),
        attachments=files,
        agent=item.get("agent") if isinstance(item.get("agent"), dict) else None,
    )
