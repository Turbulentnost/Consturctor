from __future__ import annotations

import threading
from typing import Any

from PySide6.QtCore import QEventLoop, QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QDialog, QLabel, QWidget

from app.ui.theme import COLOR_CONTENT_MUTED, app_font
from app.ui.widgets.app_dialog import AppDialog

_bridge: ConfirmBridge | None = None


class ConfirmBridge(QObject):
    """Запрос подтверждения из фонового потока → диалог в UI-потоке."""

    ask = Signal(str, object, object)  # tool_name, arguments, threading.Event

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.ask.connect(self._on_ask, Qt.ConnectionType.QueuedConnection)
        self._pending_done: threading.Event | None = None
        self._active_dialog: AppDialog | None = None

    @Slot(str, object, object)
    def _on_ask(self, tool_name: str, arguments: object, done: object) -> None:
        parent = self.parent()
        if not isinstance(parent, QWidget):
            parent = None
        args = arguments if isinstance(arguments, dict) else {}
        preview = "\n".join(f"{k}: {v}" for k, v in list(args.items())[:8])

        dialog = AppDialog(
            "Подтверждение действия",
            message=f"Разрешить выполнение «{tool_name}»?",
            parent=parent,
            primary="Разрешить",
            secondary="Отмена",
        )
        if preview:
            detail = QLabel(preview)
            detail.setWordWrap(True)
            detail.setFont(app_font(12))
            detail.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            dialog.add_body(detail)

        self._active_dialog = dialog
        loop = QEventLoop()
        dialog.finished.connect(loop.quit)
        dialog.show()
        loop.exec()
        approved = dialog.result() == QDialog.DialogCode.Accepted
        self._active_dialog = None

        if isinstance(done, threading.Event) and not done.is_set():
            setattr(done, "_approved", approved)
            done.set()

    def confirm(self, tool_name: str, arguments: dict[str, Any]) -> bool:
        done = threading.Event()
        self._pending_done = done
        try:
            self.ask.emit(tool_name, arguments, done)
            done.wait()
            return bool(getattr(done, "_approved", False))
        finally:
            if self._pending_done is done:
                self._pending_done = None

    def reject_pending(self) -> None:
        pending = self._pending_done
        if pending is not None:
            setattr(pending, "_approved", False)
            pending.set()
        dialog = self._active_dialog
        if dialog is not None:
            dialog.reject()


def install_confirm_bridge(parent: QWidget) -> ConfirmBridge:
    global _bridge
    _bridge = ConfirmBridge(parent)
    return _bridge


def confirm_from_worker(tool_name: str, arguments: dict[str, Any]) -> bool:
    if _bridge is None:
        return False
    return _bridge.confirm(tool_name, arguments)


def reject_pending_confirm() -> None:
    if _bridge is not None:
        _bridge.reject_pending()


def clear_confirm_bridge() -> None:
    global _bridge
    _bridge = None
