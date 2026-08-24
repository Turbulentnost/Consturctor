"""Push desktop tool_request from Celery to the API websocket via Redis."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.notifications.hub import hub

logger = logging.getLogger(__name__)

TOOL_CHANNEL = "constructor:tool-live"


def push_tool_request(user_id: str, payload: dict[str, Any]) -> None:
    uid = (user_id or "").strip()
    if not uid or not isinstance(payload, dict):
        return
    message = dict(payload)
    message["type"] = "tool_request"
    hub.schedule_push(uid, message)
    try:
        from app.services.sessions import _redis

        client = _redis()
        if client is None:
            return
        client.publish(
            TOOL_CHANNEL,
            json.dumps({"user_id": uid, "payload": message}, ensure_ascii=False, default=str),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tool live redis publish failed user=%s: %s", uid, exc)
