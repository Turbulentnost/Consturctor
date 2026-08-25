from __future__ import annotations

from app.config import settings

INBOUND_QUEUE = "chat.inbound"
OUTBOUND_QUEUE = "chat.outbound"
INBOUND_DLQ = "chat.inbound.dlq"
RR_KEY = "constructor:chat:support:rr_index"


def rabbitmq_url() -> str:
    return (settings.rabbitmq_url or "").strip()


def support_user_ids() -> list[str]:
    raw = (settings.chat_support_user_ids or "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]
