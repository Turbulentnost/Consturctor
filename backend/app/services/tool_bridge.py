"""SSE tool bridge: backend asks desktop to run a tool, waits for POST result."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


DEFAULT_TIMEOUT_S = 600.0


class ToolBridgeError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    payload: dict[str, Any] | None = None
    user_id: str = ""


class ToolBridgeRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_request: dict[str, _Pending] = {}
        self._run_owners: dict[str, str] = {}

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def new_request_id(self) -> str:
        return str(uuid.uuid4())

    def register_run(self, run_id: str, user_id: str) -> None:
        with self._lock:
            self._run_owners[run_id] = user_id

    def unregister_run(self, run_id: str) -> None:
        with self._lock:
            self._run_owners.pop(run_id, None)

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
        with self._lock:
            owner = self._run_owners.get(run_id)
            if owner is None:
                raise ToolBridgeError("Неизвестный agent run", status_code=404)
            if owner != user_id:
                raise ToolBridgeError("Нет доступа к этому run", status_code=403)
            pending = self._by_request.get(request_id)
            if pending is None:
                # Late ACK after timeout or a duplicate POST — do not fail the desktop.
                return
            if pending.user_id and pending.user_id != user_id:
                raise ToolBridgeError("Нет доступа к этому request", status_code=403)
            pending.payload = {
                "ok": bool(ok),
                "result": result if isinstance(result, dict) else {},
                "error": str(error or ""),
            }
            pending.event.set()


tool_bridge = ToolBridgeRegistry()
