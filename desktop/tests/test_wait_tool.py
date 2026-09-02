from __future__ import annotations

from app.tools.ac.wait_tool import AgentWaitTool


def test_agent_wait_sleeps_requested_seconds() -> None:
    result = AgentWaitTool().execute({"seconds": 0.2})
    assert result.ok is True
    assert result.output_data["requested_seconds"] == 0.2
    assert result.output_data["waited_seconds"] >= 0.2
    assert result.output_data["cancelled"] is False


def test_agent_wait_rejects_non_number() -> None:
    result = AgentWaitTool().execute({"seconds": "nope"})
    assert result.ok is False
    assert result.error_type == "INVALID_SECONDS"
