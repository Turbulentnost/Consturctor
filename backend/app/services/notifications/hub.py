"""In-memory WebSocket hub: user_id → connected desktops."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from app.services.sessions import DEFAULT_CLIENT, normalize_client

logger = logging.getLogger(__name__)


class NotificationHub:
    def __init__(self) -> None:
        self._sockets: dict[str, set[WebSocket]] = {}
        self._ws_session: dict[int, str] = {}
        self._ws_client: dict[int, str] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def add(
        self,
        user_id: str,
        ws: WebSocket,
        *,
        session_id: str = "",
        client: str = DEFAULT_CLIENT,
    ) -> None:
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = getattr(self, "_loop", None)
        self._sockets.setdefault(user_id, set()).add(ws)
        if session_id:
            self._ws_session[id(ws)] = session_id
        self._ws_client[id(ws)] = normalize_client(client)

    def _client_of(self, ws: WebSocket) -> str:
        return self._ws_client.get(id(ws), DEFAULT_CLIENT)

    def _sockets_for(self, user_id: str, client: str = "") -> list[WebSocket]:
        group = list(self._sockets.get(user_id) or ())
        if not client:
            return group
        wanted = normalize_client(client)
        return [item for item in group if self._client_of(item) == wanted]

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
        self._ws_session.pop(id(ws), None)
        self._ws_client.pop(id(ws), None)
        if not group:
            self._sockets.pop(user_id, None)

    def is_online(self, user_id: str) -> bool:
        return bool(self._sockets.get(user_id))

    async def kick_user(
        self,
        user_id: str,
        *,
        client: str = "",
        reason: str = "session_replaced",
    ) -> None:
        group = self._sockets_for(user_id, client)
        if not group:
            return
        text = json.dumps(
            {
                "type": "session_replaced",
                "message": "Выполнен вход на другом устройстве. Этот сеанс завершён.",
            },
            ensure_ascii=False,
        )
        for ws in group:
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001
                logger.warning("Failed to notify kicked session user=%s", user_id)
            try:
                await ws.close(code=4001)
            except Exception:  # noqa: BLE001
                pass
            self.remove(user_id, ws)
        _ = reason

    async def replace(
        self,
        user_id: str,
        ws: WebSocket,
        *,
        session_id: str = "",
        client: str = DEFAULT_CLIENT,
    ) -> None:
        client = normalize_client(client)
        previous = [item for item in self._sockets_for(user_id, client) if item is not ws]
        if previous:
            text = json.dumps(
                {
                    "type": "session_replaced",
                    "message": "Выполнен вход на другом устройстве. Этот сеанс завершён.",
                },
                ensure_ascii=False,
            )
            for other in previous:
                try:
                    await other.send_text(text)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await other.close(code=4001)
                except Exception:  # noqa: BLE001
                    pass
                self.remove(user_id, other)
        self.add(user_id, ws, session_id=session_id, client=client)

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
