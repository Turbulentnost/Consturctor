"""Push live board snapshots to the desktop over the notification websocket.

Celery workers do not hold WebSocket connections, so the snapshot is also
published on Redis and relayed by the API process.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.services.notifications.hub import hub
from app.services.workflows.board import get_workflow_board

logger = logging.getLogger(__name__)

BOARD_CHANNEL = "constructor:board-live"


def push_board_updated(
    db: Session,
    *,
    user_id: str,
    workflow_id: str = "",
    run_id: str = "",
    status: str = "",
    reason: str = "",
) -> dict[str, Any] | None:
    uid = (user_id or "").strip()
    if not uid:
        return None
    try:
        board = get_workflow_board(db, user_id=uid)
        payload: dict[str, Any] = {
            "type": "board_updated",
            "workflow_id": (workflow_id or "").strip(),
            "run_id": (run_id or "").strip(),
            "status": (status or "").strip(),
            "reason": (reason or "").strip(),
            "stats": board.stats.model_dump(mode="json"),
            "agents": [item.model_dump(mode="json") for item in board.agents],
            "events": [item.model_dump(mode="json") for item in board.events],
        }
    except Exception:  # noqa: BLE001
        logger.exception("Board live snapshot failed user=%s", uid)
        return None
    hub.schedule_push(uid, payload)
    _publish_redis(uid, payload)
    return payload


def _publish_redis(user_id: str, payload: dict[str, Any]) -> bool:
    try:
        from app.services.sessions import _redis

        client = _redis()
        if client is None:
            return False
        client.publish(
            BOARD_CHANNEL,
            json.dumps({"user_id": user_id, "payload": payload}, ensure_ascii=False, default=str),
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Board live redis publish failed user=%s: %s", user_id, exc)
        return False


async def relay_board_message(raw: Any) -> None:
    if not raw:
        return
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if not isinstance(raw, str):
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(data, dict):
        return
    user_id = str(data.get("user_id") or "").strip()
    payload = data.get("payload")
    if not user_id or not isinstance(payload, dict):
        return
    raw_client = data.get("client")
    client = raw_client.strip() if isinstance(raw_client, str) else ""
    await hub.push(user_id, payload, client=client)
