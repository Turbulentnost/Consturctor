"""Human-in-the-loop: уровень 1 — запись и прочие операции только после подтверждения."""

from __future__ import annotations

import json
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

AUTONOMY_LEVEL = 1
HUMAN_REJECTED = "отклонено человеком"

_READ_EXACT = frozenset(
    {
        "web_search",
        "site_browser",
        "browser.search_web",
        "browser.open_page",
        "browser.list_installed_browsers",
        "browser.screenshot",
        "browser.get_page_html",
        "outlook.search_mail",
        "outlook.read_calendar",
        "excel.list_files",
        "excel.read_workbook",
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.sql_query",
        "agent.wait",
        "users.list",
        "notify.send",
        "agent.schedule",
        "agent.schedule.cancel",
    }
)
_READ_PREFIXES = ("onec.search_", "onec.get_", "imap.")

_host: "_ConfirmHost | None" = None
_reveal: Callable[[], None] | None = None


def is_read_tool(name: str) -> bool:
    tool = (name or "").strip()
    if tool in _READ_EXACT:
        return True
    return any(tool.startswith(prefix) for prefix in _READ_PREFIXES)


def install_confirm_host(parent: QObject | None = None) -> None:
    """Создать диалог подтверждения на GUI-потоке (вызывать из окна приложения)."""
    global _host
    if _host is None:
        _host = _ConfirmHost(parent)


def set_reveal_callback(callback: Callable[[], None] | None) -> None:
    global _reveal
    _reveal = callback


def confirm_level1_tool(tool: str, arguments: dict | None = None) -> bool:
    """True — можно вызывать инструмент. Read-инструменты без диалога."""
    if is_read_tool(tool):
        return True
    if QApplication.instance() is None:
        return False
    return _bridge().confirm(tool, arguments or {})


class _ConfirmHost(QObject):
    asked = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ok = False
        self.asked.connect(self._on_ask, Qt.ConnectionType.BlockingQueuedConnection)

    def confirm(self, tool: str, arguments: dict) -> bool:
        preview = _preview_arguments(arguments)
        app = QApplication.instance()
        if app is not None and QThread.currentThread() is app.thread():
            return self._show(tool, preview)
        self.asked.emit(tool, preview)
        return self._ok

    @Slot(str, str)
    def _on_ask(self, tool: str, preview: str) -> None:
        self._ok = self._show(tool, preview)

    def _show(self, tool: str, preview: str) -> bool:
        if _reveal is not None:
            try:
                _reveal()
            except Exception:  # noqa: BLE001
                pass
        parent = _active_window()
        text = f"Агент хочет выполнить «{tool}»."
        if preview:
            text += f"\n\nАргументы:\n{preview}"
        text += "\n\nРазрешить выполнение? Без подтверждения операция будет отклонена."
        answer = QMessageBox.question(
            parent,
            "Подтверждение человека",
            text,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return answer == QMessageBox.StandardButton.Ok


def _bridge() -> _ConfirmHost:
    global _host
    app = QApplication.instance()
    if _host is None:
        _host = _ConfirmHost()
        if app is not None and _host.thread() is not app.thread():
            _host.moveToThread(app.thread())
    return _host


def _active_window() -> QWidget | None:
    app = QApplication.instance()
    if app is None:
        return None
    return app.activeWindow()


def _preview_arguments(arguments: dict) -> str:
    if not arguments:
        return ""
    try:
        text = json.dumps(arguments, ensure_ascii=False, indent=2, default=str)
    except TypeError:
        text = str(arguments)
    if len(text) > 400:
        return text[:400].rstrip() + "…"
    return text
