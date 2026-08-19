from app.tools.hitl import (
    explain_tool,
    host_is_eligible,
    needs_confirmation,
    never_confirm,
    set_away_notify_callback,
    workflow_id_from_arguments,
)
from app.tools.hitl import _notify_away


def test_notify_send_never_asks_hitl() -> None:
    assert never_confirm("notify.send")
    assert never_confirm("notify")
    assert not needs_confirmation("notify.send")
    assert not needs_confirmation("notify")


def test_read_tools_do_not_ask_hitl() -> None:
    assert not needs_confirmation("onec.odata_get")
    assert not needs_confirmation("onec.odata_catalog")
    assert not needs_confirmation("users.list")
    assert not needs_confirmation("imap.fetch")


def test_write_tools_need_confirmation() -> None:
    assert needs_confirmation("onec.odata_post")
    assert needs_confirmation("onec.odata_patch")
    assert needs_confirmation("onec.attach_file")
    assert needs_confirmation("outlook.send_mail")


def test_workflow_id_from_arguments() -> None:
    assert workflow_id_from_arguments({"workflow_id": "wf-1"}) == "wf-1"
    assert workflow_id_from_arguments({"agent_id": "wf-2"}) == "wf-2"
    assert (
        workflow_id_from_arguments({"runtime_context": {"workflow_id": "wf-3"}}) == "wf-3"
    )
    assert workflow_id_from_arguments({}) == ""


def test_other_agent_host_does_not_steal_card() -> None:
    assert host_is_eligible(wanted="wf-a", host_workflow_id="wf-b", visible=True) is False
    assert host_is_eligible(wanted="wf-a", host_workflow_id="wf-a", visible=True) is True
    assert host_is_eligible(wanted="wf-a", host_workflow_id="wf-a", visible=False) is False


def test_unbound_visible_host_can_take_card() -> None:
    assert host_is_eligible(wanted="wf-a", host_workflow_id="", visible=True) is True


def test_invisible_host_never_shows_card() -> None:
    assert host_is_eligible(wanted="", host_workflow_id="wf-a", visible=False) is False


def test_explain_odata_post_is_human() -> None:
    title, text = explain_tool(
        "onec.odata_post",
        {
            "entity": "Document_СлужебнаяЗаписка",
            "body": {
                "Number": "123",
                "Date": "2026-06-26",
                "Posted": False,
                "Comment": "СЗ №123: проверка по обязательному составу — неполная.",
            },
        },
    )
    assert title == "Запись в 1С"
    assert "созда" in text.lower()
    assert "СлужебнаяЗаписка" in text
    assert "номер 123" in text
    assert "черновик" in text.lower()


def test_explain_unknown_tool_has_fallback() -> None:
    title, text = explain_tool("custom.write", {})
    assert title == "custom.write"
    assert "внешн" in text.lower()


def test_away_notify_callback_keeps_pending_loop_intact() -> None:
    seen: dict[str, str] = {}

    def on_away(workflow_id: str, tool: str, preview: str) -> None:
        seen["workflow_id"] = workflow_id
        seen["tool"] = tool
        seen["preview"] = preview

    set_away_notify_callback(on_away)
    try:
        _notify_away("wf-1", "onec.odata_post", '{"entitySet": "Catalog_Foo"}')
    finally:
        set_away_notify_callback(None)
    assert seen["workflow_id"] == "wf-1"
    assert seen["tool"] == "onec.odata_post"
    assert "Запись в 1С" in seen["preview"]
    assert "Catalog_Foo" in seen["preview"]
