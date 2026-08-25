from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.tools import hitl as hitl_mod
from app.tools.hitl import (
    HitlConfirmCard,
    confirm_level1_tool,
    explain_tool,
    has_pending_for,
    host_is_eligible,
    needs_confirmation,
    never_confirm,
    notification_opens_live,
    register_inline_host,
    set_away_notify_callback,
    unregister_inline_host,
    workflow_id_from_arguments,
)
from app.tools.hitl import _notify_away


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


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
    assert not needs_confirmation("turboproject.search_projects")
    assert not needs_confirmation("turboproject.get_project")
    assert not needs_confirmation("turboproject.get_user_portfolio")


def test_write_tools_need_confirmation() -> None:
    assert needs_confirmation("onec.odata_post")
    assert needs_confirmation("onec.odata_patch")
    assert needs_confirmation("onec.attach_file")
    assert needs_confirmation("outlook.send_mail")
    assert needs_confirmation("outlook.create_event")
    assert not needs_confirmation("outlook.read_calendar")


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
    assert "Catalog_Foo" not in seen["preview"]


def test_explain_excel_mentions_filename_not_json() -> None:
    title, text = explain_tool(
        "excel.create_workbook",
        {"filename": "kalendar.xlsx", "rows": [1, 2, 3]},
    )
    assert title == "Создание Excel"
    assert "kalendar.xlsx" in text
    assert "{" not in text


def test_confirm_card_is_compact_without_parameters() -> None:
    _ensure_app()
    card = HitlConfirmCard(
        "excel.create_workbook",
        '{"filename": "a.xlsx", "rows": []}',
        arguments={"filename": "a.xlsx"},
    )
    assert card._params.isHidden()
    assert card._body.isHidden()
    assert card._hint.isHidden()
    assert not card._title.isHidden()
    assert not card._tech.isHidden()
    assert not card._what.isHidden()
    assert not card._buttons.isHidden()
    assert "{" not in card._what.text()
    assert "Параметры" not in card._title.text()
    assert "a.xlsx" in card._what.text()


def test_set_resolved_collapses_to_grey_receipt() -> None:
    _ensure_app()
    card = HitlConfirmCard("excel.create_workbook", '{"sheets": 1}', arguments={})
    assert not card._buttons.isHidden()
    assert card._params.isHidden()
    assert card._body.isHidden()
    card.set_resolved(True)
    assert card._buttons.isHidden()
    assert card._title.isHidden()
    assert card._params.isHidden()
    assert card._what.isHidden()
    assert card._hint.isHidden()
    assert not card._status.isHidden()
    assert card.resolved_text() == "Вы подтвердили: Создание Excel"
    assert "#F4F7F6" in card.styleSheet()
    card.set_resolved(False)
    assert card.resolved_text() == "Вы отклонили: Создание Excel"
    assert card._buttons.isHidden()


def test_show_always_notifies_even_with_visible_host() -> None:
    app = _ensure_app()
    seen: list[tuple[str, str, str]] = []

    def on_away(workflow_id: str, tool: str, preview: str) -> None:
        seen.append((workflow_id, tool, preview))

    class _Host(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.cards: list[QWidget] = []
            QVBoxLayout(self)

        def attach_hitl_card(self, card: QWidget) -> None:
            self.cards.append(card)
            self.layout().addWidget(card)

    host = _Host()
    host.show()
    app.processEvents()
    set_away_notify_callback(on_away)
    register_inline_host(host, "wf-live")
    try:

        def accept_pending() -> None:
            for item in list(hitl_mod._pending):
                item.card._accept.click()

        QTimer.singleShot(0, accept_pending)
        ok = confirm_level1_tool("excel.create_workbook", {"workflow_id": "wf-live"})
    finally:
        unregister_inline_host(host)
        set_away_notify_callback(None)
        host.close()
    assert ok is True
    assert host.cards
    assert seen
    assert seen[0][0] == "wf-live"
    assert seen[0][1] == "excel.create_workbook"


def test_notification_opens_live_when_pending() -> None:
    _ensure_app()
    assert notification_opens_live("wf-pending") is False
    item = hitl_mod._PendingConfirm(workflow_id="wf-pending", card=QWidget())
    hitl_mod._pending.append(item)
    try:
        assert has_pending_for("wf-pending") is True
        assert notification_opens_live("wf-pending") is True
        assert notification_opens_live("other") is False
        item.answered = True
        assert has_pending_for("wf-pending") is False
        assert notification_opens_live("wf-pending") is False
    finally:
        if item in hitl_mod._pending:
            hitl_mod._pending.remove(item)
