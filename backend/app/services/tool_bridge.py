"""SSE tool bridge: backend asks desktop to run a tool, waits for POST result."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any


DEFAULT_TIMEOUT_S = 600.0
CANCELLED_ERROR = "остановлено пользователем"


class ToolBridgeError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


class AgentCancelled(RuntimeError):
    def __init__(self, message: str = "Остановлено пользователем.") -> None:
        super().__init__(message)


@dataclass
class _Pending:
    event: threading.Event = field(default_factory=threading.Event)
    payload: dict[str, Any] | None = None
    user_id: str = ""
    run_id: str = ""


@dataclass
class _RunMeta:
    user_id: str
    workflow_id: str = ""
    cursor_agent_id: str = ""
    cursor_run_id: str = ""


class ToolBridgeRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_request: dict[str, _Pending] = {}
        self._run_owners: dict[str, str] = {}
        self._run_meta: dict[str, _RunMeta] = {}
        self._run_requests: dict[str, set[str]] = {}
        self._cancelled: set[str] = set()
        self._latest_by_user: dict[str, str] = {}
        self._latest_by_workflow: dict[tuple[str, str], str] = {}
        self._inbox: dict[str, list[str]] = {}

    def new_run_id(self) -> str:
        return str(uuid.uuid4())

    def new_request_id(self) -> str:
        return str(uuid.uuid4())

    def register_run(self, run_id: str, user_id: str, workflow_id: str = "") -> None:
        with self._lock:
            self._run_owners[run_id] = user_id
            self._run_meta[run_id] = _RunMeta(user_id=user_id, workflow_id=workflow_id)
            self._run_requests.setdefault(run_id, set())
            self._inbox.setdefault(run_id, [])
            self._latest_by_user[user_id] = run_id
            if workflow_id:
                self._latest_by_workflow[(user_id, workflow_id)] = run_id
            self._cancelled.discard(run_id)

    def unregister_run(self, run_id: str) -> None:
        with self._lock:
            meta = self._run_meta.pop(run_id, None)
            self._run_owners.pop(run_id, None)
            self._run_requests.pop(run_id, None)
            self._inbox.pop(run_id, None)
            self._cancelled.discard(run_id)
            if meta and meta.workflow_id:
                key = (meta.user_id, meta.workflow_id)
                if self._latest_by_workflow.get(key) == run_id:
                    self._latest_by_workflow.pop(key, None)

    def set_cursor(self, run_id: str, *, agent_id: str, cursor_run_id: str) -> None:
        with self._lock:
            meta = self._run_meta.get(run_id)
            if meta is None:
                return
            meta.cursor_agent_id = agent_id
            meta.cursor_run_id = cursor_run_id

    def cursor_of(self, run_id: str) -> tuple[str, str]:
        with self._lock:
            meta = self._run_meta.get(run_id)
            if meta is None:
                return "", ""
            return meta.cursor_agent_id, meta.cursor_run_id

    def is_cancelled(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._cancelled

    def begin_wait(self, *, request_id: str, user_id: str, run_id: str = "") -> None:
        """Register waiter before emitting tool_request (avoids race with fast POST)."""
        pending = _Pending(user_id=user_id, run_id=run_id)
        with self._lock:
            if run_id and run_id in self._cancelled:
                pending.payload = {
                    "ok": False,
                    "result": {},
                    "error": CANCELLED_ERROR,
                }
                pending.event.set()
            self._by_request[request_id] = pending
            if run_id:
                self._run_requests.setdefault(run_id, set()).add(request_id)

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

    def latest_run_id(self, user_id: str, workflow_id: str = "") -> str:
        with self._lock:
            if workflow_id:
                return self._latest_by_workflow.get((user_id, workflow_id)) or ""
            return self._latest_by_user.get(user_id) or ""

    def push_chat(self, *, run_id: str, user_id: str, message: str) -> bool:
        text = (message or "").strip()
        if not text:
            return False
        with self._lock:
            owner = self._run_owners.get(run_id)
            if owner is None or owner != user_id or run_id in self._cancelled:
                return False
            self._inbox.setdefault(run_id, []).append(text)
            return True

    def drain_chat(self, run_id: str) -> list[str]:
        with self._lock:
            items = list(self._inbox.get(run_id) or [])
            if run_id in self._inbox:
                self._inbox[run_id] = []
            return items

    def request_cancel(self, *, run_id: str, user_id: str) -> dict[str, str]:
        if not run_id:
            run_id = self.latest_run_id(user_id)
        with self._lock:
            owner = self._run_owners.get(run_id)
            if owner is None:
                raise ToolBridgeError("Неизвестный agent run", status_code=404)
            if owner != user_id:
                raise ToolBridgeError("Нет доступа к этому run", status_code=403)
            self._cancelled.add(run_id)
            meta = self._run_meta.get(run_id)
            agent_id = meta.cursor_agent_id if meta else ""
            cursor_run_id = meta.cursor_run_id if meta else ""
            request_ids = list(self._run_requests.get(run_id, ()))
            for request_id in request_ids:
                pending = self._by_request.get(request_id)
                if pending is None or pending.event.is_set():
                    continue
                pending.payload = {
                    "ok": False,
                    "result": {},
                    "error": CANCELLED_ERROR,
                }
                pending.event.set()
        return {"agent_id": agent_id, "cursor_run_id": cursor_run_id}


tool_bridge = ToolBridgeRegistry()


def raise_if_cancelled(run_id: str = "") -> None:
    if run_id and tool_bridge.is_cancelled(run_id):
        raise AgentCancelled()
