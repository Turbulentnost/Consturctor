from __future__ import annotations

from app.services.onec_tools import ONEC_WRITE_TOOLS
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
    assert "onec.odata_get" not in ONEC_WRITE_TOOLS


def test_odata_post_waits_confirm_only_then_writes(monkeypatch) -> None:
    events: list[tuple] = []
    order: list[str] = []

    def on_event(event_type: str, text: str = "", extra: dict | None = None) -> None:
        events.append((event_type, extra or {}))

    monkeypatch.setattr(
        "app.services.workflows.cursor_tools.tool_bridge.new_request_id",
        lambda: "req-confirm",
    )
    monkeypatch.setattr(
        "app.services.workflows.cursor_tools.tool_bridge.begin_wait",
        lambda **kwargs: order.append("wait"),
    )

    def fake_await(**kwargs):
        order.append("confirmed")
        assert kwargs.get("timeout_s") == CONFIRM_TIMEOUT_S
        return {"ok": True, "result": {"confirmed": True}}

    monkeypatch.setattr(
        "app.services.workflows.cursor_tools.tool_bridge.await_result",
        fake_await,
    )

    def fake_onec(tool, args, user_id=""):
        order.append("write")
        assert order[:2] == ["wait", "confirmed"]
        return {"ok": True, "id": "doc-1"}

    monkeypatch.setattr("app.services.agent_runtime._invoke_onec_server", fake_onec)

    set_tool_context("run-1", "user-1")
    try:
        result = invoke_creation_tool(
            tool="onec.odata_post",
            arguments={"entitySet": "Catalog_Foo"},
            on_event=on_event,
            workflow_id="wf-1",
        )
    finally:
        clear_tool_context()

    assert order == ["wait", "confirmed", "write"]
    request = next(extra for typ, extra in events if typ == "tool_request")
    assert request["confirm_only"] is True
    assert request["tool"] == "onec.odata_post"
    assert request["request_id"] == "req-confirm"
    assert result == {"ok": True, "id": "doc-1"}


def test_odata_post_rejected_does_not_write(monkeypatch) -> None:
    written = {"ok": False}

    monkeypatch.setattr(
        "app.services.workflows.cursor_tools.tool_bridge.new_request_id",
        lambda: "req-reject",
    )
    monkeypatch.setattr(
        "app.services.workflows.cursor_tools.tool_bridge.begin_wait",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.workflows.cursor_tools.tool_bridge.await_result",
        lambda **kwargs: {"ok": False, "error": "отклонено человеком"},
    )
    monkeypatch.setattr(
        "app.services.agent_runtime._invoke_onec_server",
        lambda *args, **kwargs: written.__setitem__("ok", True) or {"ok": True},
    )

    set_tool_context("run-1", "user-1")
    try:
        try:
            invoke_creation_tool(
                tool="onec.odata_post",
                arguments={"entitySet": "Catalog_Foo"},
                on_event=None,
                workflow_id="wf-1",
            )
            raise AssertionError("expected reject")
        except RuntimeError as exc:
            assert "отклонено" in str(exc)
    finally:
        clear_tool_context()
    assert not written["ok"]


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


def test_runtime_write_emits_confirm_only(monkeypatch) -> None:
    from app.services.agent_runtime import _request_desktop_tool

    events: list[dict] = []
    order: list[str] = []

    monkeypatch.setattr(
        "app.services.agent_runtime.tool_bridge.new_request_id",
        lambda: "req-rt",
    )
    monkeypatch.setattr(
        "app.services.agent_runtime.tool_bridge.begin_wait",
        lambda **kwargs: order.append("wait"),
    )
    monkeypatch.setattr(
        "app.services.agent_runtime.tool_bridge.await_result",
        lambda **kwargs: order.append("confirmed") or {"ok": True, "result": {"confirmed": True}},
    )
    monkeypatch.setattr(
        "app.services.agent_runtime._invoke_onec_server",
        lambda tool, arguments, user_id="": order.append("write") or {"ok": True},
    )

    result = _request_desktop_tool(
        events.append,
        run_id="run-1",
        user_id="user-1",
        tool="onec.odata_patch",
        arguments={"entitySet": "Catalog_Foo"},
        workflow_id="wf-1",
    )
    assert order == ["wait", "confirmed", "write"]
    request = next(item for item in events if item.get("type") == "tool_request")
    assert request["confirm_only"] is True
    assert request["tool"] == "onec.odata_patch"
    assert result == {"ok": True}


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
