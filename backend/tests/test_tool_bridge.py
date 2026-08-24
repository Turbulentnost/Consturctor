"""Unit tests for SSE tool bridge registry."""

from __future__ import annotations

import threading
import time

from app.services.tool_bridge import ToolBridgeError, ToolBridgeRegistry


def test_tool_bridge_roundtrip() -> None:
    bridge = ToolBridgeRegistry()
    run_id = bridge.new_run_id()
    request_id = bridge.new_request_id()
    user_id = "user-1"
    bridge.register_run(run_id, user_id)
    bridge.begin_wait(request_id=request_id, user_id=user_id)

    result_box: dict = {}

    def waiter() -> None:
        result_box["payload"] = bridge.await_result(request_id=request_id, timeout_s=5.0)

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.05)
    bridge.submit_result(
        run_id=run_id,
        request_id=request_id,
        user_id=user_id,
        ok=True,
        result={"count": 3},
    )
    thread.join(timeout=2.0)
    assert result_box["payload"]["ok"] is True
    assert result_box["payload"]["result"]["count"] == 3
    bridge.unregister_run(run_id)


def test_tool_bridge_rejects_wrong_user() -> None:
    bridge = ToolBridgeRegistry()
    run_id = bridge.new_run_id()
    request_id = bridge.new_request_id()
    bridge.register_run(run_id, "owner")
    bridge.begin_wait(request_id=request_id, user_id="owner")
    try:
        bridge.submit_result(
            run_id=run_id,
            request_id=request_id,
            user_id="other",
            ok=True,
            result={},
        )
        assert False, "expected ToolBridgeError"
    except ToolBridgeError as exc:
        assert exc.status_code == 403
    finally:
        bridge.unregister_run(run_id)


def test_tool_bridge_late_submit_is_ignored() -> None:
    bridge = ToolBridgeRegistry()
    run_id = bridge.new_run_id()
    request_id = bridge.new_request_id()
    bridge.register_run(run_id, "owner")
    bridge.begin_wait(request_id=request_id, user_id="owner")
    try:
        bridge.await_result(request_id=request_id, timeout_s=0.01)
        assert False, "expected timeout"
    except TimeoutError:
        pass
    bridge.submit_result(
        run_id=run_id,
        request_id=request_id,
        user_id="owner",
        ok=True,
        result={"late": True},
    )
    bridge.unregister_run(run_id)


def test_tool_bridge_redis_wakes_other_process_wait() -> None:
    store: dict[str, str] = {}
    lists: dict[str, list[str]] = {}

    class FakeRedis:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)
            lists.pop(key, None)

        def lpush(self, key, value):
            lists.setdefault(key, []).insert(0, value)

        def expire(self, key, _ttl):
            return True

        def blpop(self, key, timeout=0):
            deadline = time.time() + max(0.0, float(timeout))
            while True:
                items = lists.get(key) or []
                if items:
                    return (key, items.pop(0))
                if time.time() >= deadline:
                    return None
                time.sleep(0.02)

    fake = FakeRedis()
    worker = ToolBridgeRegistry(redis_factory=lambda: fake)
    api = ToolBridgeRegistry(redis_factory=lambda: fake)
    run_id = worker.new_run_id()
    request_id = worker.new_request_id()
    worker.register_run(run_id, "user-1")
    worker.begin_wait(request_id=request_id, user_id="user-1")
    result_box: dict = {}

    def waiter() -> None:
        result_box["payload"] = worker.await_result(request_id=request_id, timeout_s=2.0)

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.05)
    api.submit_result(
        run_id=run_id,
        request_id=request_id,
        user_id="user-1",
        ok=True,
        result={"via": "redis"},
    )
    thread.join(timeout=2.0)
    assert result_box["payload"]["result"]["via"] == "redis"
    worker.unregister_run(run_id)
