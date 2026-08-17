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
