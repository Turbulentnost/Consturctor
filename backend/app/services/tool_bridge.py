"""Tool bridge: backend asks desktop to run a tool, waits for POST result.

In-process SSE (chat) uses a local Event. Celery scheduled runs live in another
process, so the wait is also mirrored in Redis: the API can LPUSH a result and
the worker BLPOP it.
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


DEFAULT_TIMEOUT_S = 600.0
CONFIRM_TIMEOUT_S = 12 * 3600.0
_RUN_TTL_SEC = 2 * 3600
_RESULT_TTL_SEC = 120
_RUN_KEY = "constructor:tool-run:{run_id}"
_RESULT_KEY = "constructor:tool-result:{request_id}"

logger = logging.getLogger(__name__)


class ToolBridgeError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    payload: dict[str, Any] | None = None
    user_id: str = ""


def _live_redis():
    from app.services.sessions import _redis

    return _redis()


class ToolBridgeRegistry:
    def __init__(self, redis_factory: Callable[[], Any] | None = None) -> None:
        self._lock = threading.Lock()
        self._by_request: dict[str, _Pending] = {}
        self._run_owners: dict[str, str] = {}
        self._redis_factory = redis_factory

    def _redis(self):
        if self._redis_factory is None:
            return None
        try:
            return self._redis_factory()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool bridge redis unavailable: %s", exc)
            return None

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def new_request_id(self) -> str:
        return str(uuid.uuid4())

    def register_run(self, run_id: str, user_id: str) -> None:
        with self._lock:
            self._run_owners[run_id] = user_id
        client = self._redis()
        if client is None:
            return
        try:
            client.set(_RUN_KEY.format(run_id=run_id), user_id, ex=_RUN_TTL_SEC)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool bridge register_run redis failed: %s", exc)

    def unregister_run(self, run_id: str) -> None:
        with self._lock:
            self._run_owners.pop(run_id, None)
        client = self._redis()
        if client is None:
            return
        try:
            client.delete(_RUN_KEY.format(run_id=run_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool bridge unregister_run redis failed: %s", exc)

    def begin_wait(self, *, request_id: str, user_id: str) -> None:
        """Register waiter before emitting tool_request (avoids race with fast POST)."""
        pending = _Pending(user_id=user_id)
        with self._lock:
            self._by_request[request_id] = pending

    def await_result(
        self,
        *,
        request_id: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> dict[str, Any]:
        with self._lock:
            pending = self._by_request.get(request_id)
        if pending is None:
            raise ToolBridgeError(f"Нет ожидания для request_id={request_id}", status_code=500)
        try:
            if pending.event.wait(timeout=0) and pending.payload is not None:
                return pending.payload
            client = self._redis()
            if client is not None:
                try:
                    item = client.blpop(
                        _RESULT_KEY.format(request_id=request_id),
                        timeout=max(1, int(timeout_s)),
                    )
                    if not item:
                        raise TimeoutError(
                            f"Таймаут ожидания результата инструмента ({request_id})"
                        )
                    raw = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else item
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8")
                    data = json.loads(raw)
                    if isinstance(data, dict):
                        return data
                except TimeoutError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Tool bridge blpop failed: %s", exc)
            if not pending.event.wait(timeout=timeout_s):
                raise TimeoutError(
                    f"Таймаут ожидания результата инструмента ({request_id})"
                )
            assert pending.payload is not None
            return pending.payload
        finally:
            with self._lock:
                self._by_request.pop(request_id, None)

    def wait_for_result(
        self,
        *,
        request_id: str,
        user_id: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> dict[str, Any]:
        self.begin_wait(request_id=request_id, user_id=user_id)
        return self.await_result(request_id=request_id, timeout_s=timeout_s)

    def submit_result(
        self,
        *,
        run_id: str,
        request_id: str,
        user_id: str,
        ok: bool,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        payload = {
            "ok": bool(ok),
            "result": result if isinstance(result, dict) else {},
            "error": str(error or ""),
        }
        with self._lock:
            owner = self._run_owners.get(run_id)
            pending = self._by_request.get(request_id)
        if not owner:
            owner = self._redis_owner(run_id)
        if not owner:
            raise ToolBridgeError("Неизвестный agent run", status_code=404)
        if owner != user_id:
            raise ToolBridgeError("Нет доступа к этому run", status_code=403)
        if pending is not None:
            if pending.user_id and pending.user_id != user_id:
                raise ToolBridgeError("Нет доступа к этому request", status_code=403)
            pending.payload = payload
            pending.event.set()
        pushed = self._redis_push_result(request_id, payload)
        if pending is None and not pushed:
            return

    def _redis_owner(self, run_id: str) -> str:
        client = self._redis()
        if client is None:
            return ""
        try:
            value = client.get(_RUN_KEY.format(run_id=run_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool bridge redis get run failed: %s", exc)
            return ""
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        return str(value or "")

    def _redis_push_result(self, request_id: str, payload: dict[str, Any]) -> bool:
        client = self._redis()
        if client is None:
            return False
        key = _RESULT_KEY.format(request_id=request_id)
        try:
            client.lpush(key, json.dumps(payload, ensure_ascii=False, default=str))
            client.expire(key, _RESULT_TTL_SEC)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tool bridge redis lpush failed: %s", exc)
            return False


tool_bridge = ToolBridgeRegistry(redis_factory=_live_redis)
