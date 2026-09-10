from __future__ import annotations

import pytest

from app.services.onec_tools import ONEC_TOOLS, ONEC_WRITE_TOOLS, OnecToolError, invoke_onec
from app.services.tool_bridge import CONFIRM_TIMEOUT_S
from app.services.workflows.cursor_tools import (
    clear_tool_context,
    invoke_creation_tool,
    set_tool_context,
)
from app.services.workflows.prompts import build_playbook_prompt, build_published_run_prompt


def test_confirm_timeout_is_hours() -> None:
    assert CONFIRM_TIMEOUT_S >= 12 * 3600


def test_onec_write_tools_are_create_update() -> None:
    assert "onec.odata_post" in ONEC_WRITE_TOOLS
    assert "onec.odata_patch" in ONEC_WRITE_TOOLS
    assert "onec.attach_file" in ONEC_WRITE_TOOLS
    assert "onec.erp_assignments_write" in ONEC_WRITE_TOOLS
    assert "onec.odata_get" not in ONEC_WRITE_TOOLS
    assert "onec.erp_assignments" not in ONEC_WRITE_TOOLS
    assert "onec.erp_write_probe" not in ONEC_WRITE_TOOLS


def test_write_probe_does_not_wait_confirm(monkeypatch) -> None:
    order: list[str] = []

    def fake_await(**kwargs):
        order.append("confirmed")
        return {"ok": True}

    monkeypatch.setattr(
        "app.services.workflows.cursor_tools.tool_bridge.await_result",
        fake_await,
    )
    monkeypatch.setattr(
        "app.services.agent_runtime._invoke_onec_server",
        lambda *args, **kwargs: {"ok": True, "recipe": {"tool": "onec.erp_assignments_write"}},
    )
    set_tool_context("run-1", "user-1")
    try:
        result = invoke_creation_tool(
            tool="onec.erp_write_probe",
            arguments={"workflow_id": "wf-1"},
            on_event=None,
            workflow_id="wf-1",
        )
    finally:
        clear_tool_context()
    assert "confirmed" not in order
    assert result["ok"] is True


def test_odata_write_tools_not_in_public_catalog() -> None:
    from app.services.onec_tools import ONEC_ODATA_WRITE_TOOLS

    assert ONEC_ODATA_WRITE_TOOLS.isdisjoint(ONEC_TOOLS)
    assert "onec.erp_assignments_write" in ONEC_TOOLS


def test_odata_post_is_blocked() -> None:
    with pytest.raises(OnecToolError, match="отключена"):
        invoke_onec("onec.odata_post", {"entity": "Document_Foo"})


def test_invoke_creation_tool_blocks_odata_post() -> None:
    with pytest.raises(RuntimeError, match="отключена"):
        invoke_creation_tool(
            tool="onec.odata_post",
            arguments={"entitySet": "Catalog_Foo"},
            on_event=None,
            workflow_id="wf-1",
        )


def test_odata_get_does_not_wait_confirm(monkeypatch) -> None:
    called = {"confirm": False}

    def boom(*_args, **_kwargs):
        called["confirm"] = True
        raise AssertionError("HITL must not run for onec.odata_get")

    monkeypatch.setattr(
        "app.services.workflows.cursor_tools._await_human_confirm",
        boom,
    )
    monkeypatch.setattr(
        "app.services.agent_runtime._invoke_onec_server",
        lambda tool, args, user_id="": {"ok": True, "items": []},
    )
    result = invoke_creation_tool(
        tool="onec.odata_get",
        arguments={"entitySet": "Catalog_Foo"},
        on_event=None,
    )
    assert not called["confirm"]
    assert result["ok"] is True


def test_notify_send_skips_hitl(monkeypatch) -> None:
    called = {"confirm": False, "notify": False}

    def boom(*_args, **_kwargs):
        called["confirm"] = True
        raise AssertionError("HITL must not run for notify.send")

    monkeypatch.setattr(
        "app.services.workflows.cursor_tools._await_human_confirm",
        boom,
    )
    monkeypatch.setattr(
        "app.services.workflows.cursor_tools._invoke_notify_send",
        lambda _args: called.__setitem__("notify", True) or {"ok": True, "id": "n1"},
    )
    result = invoke_creation_tool(
        tool="notify.send",
        arguments={"user_id": "u1", "title": "Просрочка"},
        on_event=None,
    )
    assert not called["confirm"]
    assert called["notify"]
    assert result["ok"] is True


def test_runtime_write_is_blocked() -> None:
    from app.services.agent_runtime import AgentRuntimeError, _request_desktop_tool

    with pytest.raises(AgentRuntimeError, match="отключена"):
        _request_desktop_tool(
            lambda _event: None,
            run_id="run-1",
            user_id="user-1",
            tool="onec.odata_patch",
            arguments={"entitySet": "Catalog_Foo"},
            workflow_id="wf-1",
        )


def test_published_prompt_notify_is_not_gated_on_hitl() -> None:
    text = build_published_run_prompt(
        instructions="Пришли уведомление",
        example_run="notify.send",
        user_message="запусти",
    )
    assert "notify.send" in text
    assert "не нужно" in text
    assert "алерт не отправлен (нужно подтверждение)" in text
    assert "не пиши «алерт не отправлен (нужно подтверждение)»" in text.casefold() or (
        "не пиши" in text and "нужно подтверждение" in text
    )


def test_playbook_prompt_notify_is_immediate() -> None:
    text = build_playbook_prompt(
        title="Контроль",
        demo_text="вызвал notify.send",
        tools=["notify.send"],
    )
    assert "notify.send" in text
    assert "не ждёт подтверждения" in text or "не откладывается" in text
