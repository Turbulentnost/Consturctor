from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

import pika

from app.modules.chat.bus.topology import connect, declare
from app.modules.chat.config import OUTBOUND_QUEUE

logger = logging.getLogger(__name__)


def publish_outbound(event: dict[str, Any]) -> None:
    try:
        connection = connect()
        try:
            channel = connection.channel()
            declare(channel)
            channel.basic_publish(
                exchange="",
                routing_key=OUTBOUND_QUEUE,
                body=json.dumps(event, ensure_ascii=False, default=str).encode("utf-8"),
                properties=pika.BasicProperties(delivery_mode=2, content_type="application/json"),
            )
        finally:
            connection.close()
    except Exception:
        logger.exception("chat outbound publish failed, dispatching inline")
        from app.modules.chat.realtime import dispatch_event

        dispatch_event(event)


def consume_outbound(on_event: Callable[[dict[str, Any]], None]) -> None:
    connection = connect()
    channel = connection.channel()
    declare(channel)
    channel.basic_qos(prefetch_count=16)

    def _on_message(_ch, method, _props, body: bytes) -> None:
        try:
            event = json.loads(body.decode("utf-8"))
            if isinstance(event, dict):
                on_event(event)
            channel.basic_ack(method.delivery_tag)
        except Exception:
            logger.exception("chat outbound consume failed")
            channel.basic_nack(method.delivery_tag, requeue=False)

    channel.basic_consume(OUTBOUND_QUEUE, _on_message)
    logger.info("chat outbound consumer listening on %s", OUTBOUND_QUEUE)
    try:
        channel.start_consuming()
    finally:
        connection.close()
