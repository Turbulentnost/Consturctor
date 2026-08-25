from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import pika

from app.modules.chat.bus.topology import connect, declare
from app.modules.chat.config import INBOUND_QUEUE

logger = logging.getLogger(__name__)


def enqueue_command(command: dict[str, Any]) -> str:
    payload = dict(command)
    client_id = str(payload.get("client_id") or "").strip() or uuid.uuid4().hex
    payload["client_id"] = client_id
    try:
        connection = connect()
        try:
            channel = connection.channel()
            declare(channel)
            channel.basic_publish(
                exchange="",
                routing_key=INBOUND_QUEUE,
                body=json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8"),
                properties=pika.BasicProperties(
                    delivery_mode=2,
                    content_type="application/json",
                    message_id=client_id,
                ),
            )
        finally:
            connection.close()
        return client_id
    except Exception:
        logger.exception("chat inbound publish failed, processing inline")
        from app.modules.chat.handler import handle_command_and_emit

        handle_command_and_emit(payload)
        return client_id
