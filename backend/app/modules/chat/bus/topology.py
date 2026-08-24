from __future__ import annotations

import logging

import pika

from app.modules.chat.config import INBOUND_DLQ, INBOUND_QUEUE, OUTBOUND_QUEUE, rabbitmq_url

logger = logging.getLogger(__name__)


def connect() -> pika.BlockingConnection:
    url = rabbitmq_url()
    if not url:
        raise RuntimeError("RABBITMQ_URL is empty")
    params = pika.URLParameters(url)
    params.heartbeat = 30
    params.blocked_connection_timeout = 10
    return pika.BlockingConnection(params)


def declare(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    channel.queue_declare(INBOUND_DLQ, durable=True)
    channel.queue_declare(
        INBOUND_QUEUE,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "",
            "x-dead-letter-routing-key": INBOUND_DLQ,
        },
    )
    channel.queue_declare(OUTBOUND_QUEUE, durable=True)
