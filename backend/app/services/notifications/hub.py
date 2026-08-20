"""In-memory WebSocket hub: user_id → connected desktops."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class NotificationHub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def add(self, user_id: str, ws: WebSocket) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = getattr(self, "_loop", None)
        self._sockets.setdefault(user_id, set()).add(ws)

    def schedule_push(self, user_id: str, payload: dict[str, Any]) -> bool:
        """Отправить с того же loop, где висит WebSocket. True — получатель онлайн, пуш поставлен в очередь."""
        import asyncio

        if not self._sockets.get(user_id):
            return False

        async def _send() -> bool:
            return await self.push(user_id, payload)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is not None:
            running.create_task(_send())
            return True
        loop = getattr(self, "_loop", None)
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(_send(), loop)
            return True
        return False

    def remove(self, user_id: str, ws: WebSocket) -> None:
        group = self._sockets.get(user_id)
        if not group:
            return
        group.discard(ws)
        if not group:
            self._sockets.pop(user_id, None)

    def is_online(self, user_id: str) -> bool:
        return bool(self._sockets.get(user_id))

    async def push(self, user_id: str, payload: dict[str, Any]) -> bool:
        group = list(self._sockets.get(user_id) or ())
        if not group:
            return False
        text = json.dumps(payload, ensure_ascii=False, default=str)
        sent = False
        for ws in group:
            try:
                await ws.send_text(text)
                sent = True
            except Exception:  # noqa: BLE001
                logger.warning("Failed to push notification to user=%s", user_id)
                self.remove(user_id, ws)
        return sent


hub = NotificationHub()
