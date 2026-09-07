"""Push scheduled agent commands to the user's desktop websocket."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.services.notifications.hub import hub
from app.services.sessions import normalize_client

logger = logging.getLogger(__name__)

DESKTOP_COMMAND_CHANNEL = "constructor:desktop-command-live"
ORCHESTRATOR_COMMAND_TYPES = frozenset(
    {"evaluate_trigger", "run_agent", "form_orchestrator", "calc_orchestrator"}
)


def _command_client(payload: dict[str, Any], client: str = "") -> str:
    if (client or "").strip():
        return normalize_client(client)
    kind = str(payload.get("type") or "").strip()
    if kind in ORCHESTRATOR_COMMAND_TYPES:
        return "orchestrator"
    return ""


def push_desktop_command(user_id: str, payload: dict[str, Any], client: str = "") -> bool:
    uid = (user_id or "").strip()
    if not uid or not isinstance(payload, dict):
        return False
    message = dict(payload)
    target = _command_client(message, client)
    delivered = hub.schedule_push(uid, message, client=target)
    try:
        from app.services.sessions import _redis

        redis_client = _redis()
        if redis_client is None:
            return delivered
        redis_client.publish(
            DESKTOP_COMMAND_CHANNEL,
            json.dumps(
                {"user_id": uid, "payload": message, "client": target},
                ensure_ascii=False,
                default=str,
            ),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Desktop command publish failed user=%s: %s", uid, exc)
        return delivered
