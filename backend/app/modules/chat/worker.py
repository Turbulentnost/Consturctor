from __future__ import annotations

import json
import logging
import sys

from app.db.session import SessionLocal, init_db
from app.modules.chat.bus.outbound import publish_outbound
from app.modules.chat.bus.topology import connect, declare
from app.modules.chat.config import INBOUND_QUEUE
from app.modules.chat.handler import handle_command

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger("chat.worker")


def run() -> None:
    init_db()
    connection = connect()
    channel = connection.channel()
    declare(channel)
    channel.basic_qos(prefetch_count=8)

    def _on_message(_ch, method, _props, body: bytes) -> None:
        try:
            command = json.loads(body.decode("utf-8"))
            with SessionLocal() as db:
                events = handle_command(db, command)
                db.commit()
            for event in events:
                publish_outbound(event)
            channel.basic_ack(method.delivery_tag)
        except Exception:
            logger.exception("chat inbound failed")
            channel.basic_nack(method.delivery_tag, requeue=False)

    channel.basic_consume(INBOUND_QUEUE, _on_message)
    logger.info("chat-worker listening on %s", INBOUND_QUEUE)
    try:
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
    finally:
        connection.close()


if __name__ == "__main__":
    try:
        run()
    except Exception:
        logger.exception("chat-worker crashed")
        sys.exit(1)
