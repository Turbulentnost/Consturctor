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


def test_tool_bridge_cancel_unblocks_wait() -> None:
    bridge = ToolBridgeRegistry()
    run_id = bridge.new_run_id()
    request_id = bridge.new_request_id()
    user_id = "user-1"
    bridge.register_run(run_id, user_id)
    bridge.begin_wait(request_id=request_id, user_id=user_id, run_id=run_id)
    result_box: dict = {}

    def waiter() -> None:
        result_box["payload"] = bridge.await_result(request_id=request_id, timeout_s=5.0)

    thread = threading.Thread(target=waiter, daemon=True)
    thread.start()
    time.sleep(0.05)
    bridge.request_cancel(run_id=run_id, user_id=user_id)
    thread.join(timeout=2.0)
    assert result_box["payload"]["ok"] is False
    assert "остановлено" in str(result_box["payload"]["error"])
    assert bridge.is_cancelled(run_id)
    bridge.unregister_run(run_id)


def test_tool_bridge_chat_inbox() -> None:
    bridge = ToolBridgeRegistry()
    run_id = bridge.new_run_id()
    bridge.register_run(run_id, "user-1", "wf-1")
    assert bridge.latest_run_id("user-1", "wf-1") == run_id
    assert bridge.push_chat(run_id=run_id, user_id="user-1", message="сделай ещё Excel")
    assert bridge.push_chat(run_id=run_id, user_id="other", message="нет") is False
    assert bridge.drain_chat(run_id) == ["сделай ещё Excel"]
    assert bridge.drain_chat(run_id) == []
    bridge.unregister_run(run_id)
    assert bridge.latest_run_id("user-1", "wf-1") == ""
