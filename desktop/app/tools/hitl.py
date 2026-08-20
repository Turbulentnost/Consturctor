"""Human-in-the-loop: карточка остаётся для редких опасных операций.

Опубликованный агент работает как Cursor: обычные tools идут без подтверждения,
чтобы он мог сам вызывать шаги и чинить ошибки."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from PySide6.QtCore import QEventLoop, QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

AUTONOMY_LEVEL = 3
HUMAN_REJECTED = "отклонено человеком"

_CONFIRM_EXACT = frozenset(
    {
        "onec.odata_post",
        "onec.odata_patch",
        "onec.attach_file",
    }
)
_READ_EXACT = frozenset()
_READ_PREFIXES = ()

_host: "_ConfirmHost | None" = None
_reveal: Callable[[], None] | None = None
_inline_hosts: list[QWidget] = []
_pending_loop: QEventLoop | None = None
_pending_ok = False

_CARD_QSS = """
QFrame#HitlCard {
    background: #E8F3FB;
    border: 1px solid #B7D4E8;
    border-radius: 16px;
}
"""
_ACCEPT_QSS = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 12px; padding: 8px 16px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_REJECT_QSS = """
QPushButton {
    background: #FFFFFF; color: #9B1C1C;
    border: 1px solid rgba(155,28,28,0.35);
    border-radius: 12px; padding: 8px 16px;
}
QPushButton:hover { background: #FFF4F4; }
QPushButton:disabled { background: #F4F7F6; color: #9DB3AD; border-color: rgba(16,24,23,0.10); }
"""


def is_read_tool(name: str) -> bool:
    tool = (name or "").strip()
    if tool in _CONFIRM_EXACT:
        return False
    return True


def install_confirm_host(parent: QObject | None = None) -> None:
    """Создать диалог подтверждения на GUI-потоке (вызывать из окна приложения)."""
    global _host
    if _host is None:
        _host = _ConfirmHost(parent)


def set_reveal_callback(callback: Callable[[], None] | None) -> None:
    global _reveal
    _reveal = callback


def register_inline_host(host: QWidget) -> None:
    if host not in _inline_hosts:
        _inline_hosts.append(host)


def unregister_inline_host(host: QWidget) -> None:
    if host in _inline_hosts:
        _inline_hosts.remove(host)


def _active_inline_host() -> QWidget | None:
    visible: QWidget | None = None
    fallback: QWidget | None = None
    for host in reversed(_inline_hosts):
        if not hasattr(host, "attach_hitl_card"):
            continue
        fallback = host
        if host.isVisible():
            visible = host
            break
    return visible or fallback


class HitlConfirmCard(QFrame):
    accepted = Signal()
    rejected = Signal()

    def __init__(self, tool: str, preview: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HitlCard")
        self.setStyleSheet(_CARD_QSS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        title = QLabel(f"Агент хочет выполнить «{tool}».")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        body = QLabel(preview or "Без аргументов.")
        body.setFont(app_font(12))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        hint = QLabel("Разрешить выполнение? Без подтверждения операция будет отклонена.")
        hint.setFont(app_font(11))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #5B6B74; background: transparent;")
        self._status = QLabel("")
        self._status.setFont(app_font(11, QFont.Weight.DemiBold))
        self._status.setStyleSheet("color: #08745F; background: transparent;")
        self._status.hide()
        self._reject = QPushButton("не принимать")
        self._reject.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reject.setFixedHeight(34)
        self._reject.setFont(app_font(12, QFont.Weight.DemiBold))
        self._reject.setStyleSheet(_REJECT_QSS)
        self._accept = QPushButton("принять")
        self._accept.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accept.setFixedHeight(34)
        self._accept.setMinimumWidth(110)
        self._accept.setFont(app_font(12, QFont.Weight.DemiBold))
        self._accept.setStyleSheet(_ACCEPT_QSS)
        self._reject.clicked.connect(self.rejected.emit)
        self._accept.clicked.connect(self.accepted.emit)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 4, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(self._reject, 0)
        buttons.addStretch(1)
        buttons.addWidget(self._accept, 0)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)
        lay.addWidget(title)
        if preview:
            lay.addWidget(body)
        lay.addWidget(hint)
        lay.addWidget(self._status)
        lay.addLayout(buttons)

    def set_resolved(self, accepted: bool) -> None:
        self._reject.setEnabled(False)
        self._accept.setEnabled(False)
        self._status.setText("Принято" if accepted else "Отклонено")
        self._status.setStyleSheet(
            ("color: #08745F; background: transparent;" if accepted else "color: #9B1C1C; background: transparent;")
        )
        self._status.show()


def _auto_approve_enabled() -> bool:
    return os.environ.get("AUTO_APPROVE_AGENT_TOOLS", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def reject_pending_confirm() -> None:
    global _pending_ok, _pending_loop
    loop = _pending_loop
    _pending_ok = False
    if loop is not None:
        loop.quit()


def confirm_level1_tool(
    tool: str,
    arguments: dict | None = None,
    *,
    auto_approve: bool = False,
) -> bool:
    """True — можно вызывать инструмент. Read-инструменты без диалога."""
    if auto_approve or _auto_approve_enabled():
        return True
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
        host = _active_inline_host()
        if host is not None:
            return self._show_inline(host, tool, preview)
        return self._show_box(tool, preview)

    def _show_inline(self, host: QWidget, tool: str, preview: str) -> bool:
        global _pending_loop, _pending_ok
        loop = QEventLoop(self)
        _pending_loop = loop
        _pending_ok = False
        answered = False
        card = HitlConfirmCard(tool, preview)

        def _accept() -> None:
            nonlocal answered
            global _pending_ok
            answered = True
            _pending_ok = True
            card.set_resolved(True)
            loop.quit()

        def _reject() -> None:
            nonlocal answered
            global _pending_ok
            answered = True
            _pending_ok = False
            card.set_resolved(False)
            loop.quit()

        card.accepted.connect(_accept)
        card.rejected.connect(_reject)
        attach = getattr(host, "attach_hitl_card", None)
        if callable(attach):
            attach(card)
        # Rebuilds or window activate can stop the loop without a click.
        # Do not treat that as «отклонено человеком».
        while not answered:
            loop.exec()
        _pending_loop = None
        return _pending_ok

    def _show_box(self, tool: str, preview: str) -> bool:
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
    if len(text) > 4000:
        return text[:4000].rstrip() + "…"
    return text
