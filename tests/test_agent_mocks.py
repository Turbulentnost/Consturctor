from __future__ import annotations

import importlib

import pytest

from platform_contracts.tools import ToolResult


@pytest.fixture
def orchestrator_module(monkeypatch):
    monkeypatch.setenv("USE_STUBS", "true")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    module = importlib.import_module("platform_orchestrator.service")
    importlib.reload(module)
    return module


def test_list_mock_scenarios():
    from platform_orchestrator.agent_mocks import list_mock_scenarios

    items = list_mock_scenarios()
    assert len(items) >= 5
    assert any(item["id"] == "mail_inbound" for item in items)


def test_simulate_mail_inbound(orchestrator_module, monkeypatch):
    calls: list[str] = []

    def fake_http(run_id, tool_name, payload):
        calls.append(tool_name)
        return ToolResult(ok=True, tool_name=tool_name, data={"summary": f"stub {tool_name}"})

    monkeypatch.setattr(orchestrator_module, "invoke_tool_http", fake_http)
    result = orchestrator_module.simulate_mock_scenario(
        "mail_inbound",
        department="Demo",
        user_id="test",
    )
    assert result["status"] == "done"
    assert calls == ["imap.list_unread", "imap.fetch_message", "imap.fetch_attachments"]
    assert any(step["phase"] == "plan" for step in result["steps"])
    assert any(step["phase"] == "tool" for step in result["steps"])


def test_simulate_unknown_scenario(orchestrator_module):
    with pytest.raises(KeyError):
        orchestrator_module.simulate_mock_scenario("missing-scenario")
