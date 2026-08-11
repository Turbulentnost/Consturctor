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


def test_list_sandbox_tests():
    from platform_orchestrator.tool_sandbox import SANDBOX_ORDER, list_sandbox_tests

    items = list_sandbox_tests()
    assert len(items) == len(SANDBOX_ORDER)
    assert [item["id"] for item in items] == list(SANDBOX_ORDER)
    assert any(item["id"] == "onec_incoming" for item in items)
    assert any(item["id"] == "shell_ls" for item in items)
    assert any(item["id"] == "fs_list" for item in items)
    assert any(item["id"] == "com_list_apps" for item in items)


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


def test_simulate_sandbox_onec(orchestrator_module, monkeypatch):
    calls: list[str] = []

    def fake_http(run_id, tool_name, payload):
        calls.append(tool_name)
        return ToolResult(ok=True, tool_name=tool_name, data={"summary": f"stub {tool_name}"})

    monkeypatch.setattr(orchestrator_module, "invoke_tool_http", fake_http)
    result = orchestrator_module.simulate_sandbox_test(
        "onec_incoming",
        department="Demo",
        user_id="test",
    )
    assert result["status"] == "done"
    assert calls == ["onec.odata_get"]


def test_simulate_all_sandbox(orchestrator_module, monkeypatch):
    from platform_orchestrator.tool_sandbox import SANDBOX_ORDER

    calls: list[str] = []

    def fake_http(run_id, tool_name, payload):
        calls.append(tool_name)
        return ToolResult(ok=True, tool_name=tool_name, data={"summary": f"stub {tool_name}"})

    monkeypatch.setattr(orchestrator_module, "invoke_tool_http", fake_http)
    result = orchestrator_module.simulate_all_sandbox_tests(
        department="Demo",
        user_id="test",
    )
    assert result["status"] == "done"
    assert result["count"] == len(SANDBOX_ORDER)
    assert result["failed"] == 0
    assert "onec.odata_get" in calls
    assert "shell.run" in calls
    assert "fs.list" in calls
    assert "com.list_apps" in calls


def test_simulate_unknown_scenario(orchestrator_module):
    with pytest.raises(KeyError):
        orchestrator_module.simulate_mock_scenario("missing-scenario")


def test_simulate_unknown_sandbox(orchestrator_module):
    with pytest.raises(KeyError):
        orchestrator_module.simulate_sandbox_test("missing-test")
