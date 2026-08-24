from __future__ import annotations

from collections.abc import Callable


def is_chat_event(payload: dict) -> bool:
    return str(payload.get("type") or "") in {
        "chat_message",
        "chat_receipt",
        "presence",
        "ticket_updated",
        "thread_opened",
    }


def dispatch(payload: dict, handler: Callable[[dict], None]) -> None:
    if is_chat_event(payload):
        handler(payload)
