"""Push scheduled agent commands to the user's desktop websocket."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.notifications.hub import hub

logger = logging.getLogger(__name__)

DESKTOP_COMMAND_CHANNEL = "constructor:desktop-command-live"


def push_desktop_command(user_id: str, payload: dict[str, Any]) -> bool:
    uid = (user_id or "").strip()
    if not uid or not isinstance(payload, dict):
        return False
    message = dict(payload)
    delivered = hub.schedule_push(uid, message)
    try:
        from app.services.sessions import _redis

        client = _redis()
        if client is None:
            return delivered
        client.publish(
            DESKTOP_COMMAND_CHANNEL,
            json.dumps({"user_id": uid, "payload": message}, ensure_ascii=False, default=str),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Desktop command publish failed user=%s: %s", uid, exc)
        return delivered
