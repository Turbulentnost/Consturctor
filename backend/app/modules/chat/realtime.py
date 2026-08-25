from __future__ import annotations

import logging
from typing import Any

from app.services.notifications.hub import hub

logger = logging.getLogger(__name__)


def dispatch_event(event: dict[str, Any]) -> None:
    user_ids = [str(item) for item in (event.get("user_ids") or []) if item]
    payload = {key: value for key, value in event.items() if key != "user_ids"}
    for user_id in user_ids:
        hub.schedule_push(user_id, payload)
