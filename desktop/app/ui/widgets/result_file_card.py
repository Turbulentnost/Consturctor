"""Карточка документа в ленте: открыть и сохранить к себе."""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

_CARD_QSS = """
QFrame#ResultFileCard {
    background: #F4F7F6;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 12px;
}
"""
_SAVE_QSS = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 10px; padding: 6px 12px;
}
QPushButton:hover { background: #0A8670; }
"""
_OPEN_QSS = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 10px; padding: 6px 12px;
}
QPushButton:hover { background: #F4F7F6; }
"""

_bridge: "_ResultFileBridge | None" = None


class ResultFileCard(QFrame):
    def __init__(self, path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = "file"
        self._path = Path(path)
        self.setObjectName("ResultFileCard")
        self.setStyleSheet(_CARD_QSS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        caption = QLabel("Файл результата")
        caption.setFont(app_font(11))
        caption.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        name = QLabel(self._path.name)
        name.setFont(app_font(13, QFont.Weight.DemiBold))
        name.setWordWrap(True)
        name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        save = QPushButton("Сохранить у себя")
        save.setCursor(Qt.CursorShape.PointingHandCursor)
        save.setFont(app_font(12, QFont.Weight.DemiBold))
        save.setFixedHeight(32)
        save.setStyleSheet(_SAVE_QSS)
        save.clicked.connect(self._save)
        open_btn = QPushButton("Открыть")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        open_btn.setFixedHeight(32)
        open_btn.setStyleSheet(_OPEN_QSS)
        open_btn.clicked.connect(self._open)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(8)
        buttons.addWidget(save, 0)
        buttons.addWidget(open_btn, 0)
        buttons.addStretch(1)
        root.addWidget(caption)
        root.addWidget(name)
        root.addLayout(buttons)

    def _open(self) -> None:
        if not self._path.is_file():
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path)))

    def _save(self) -> None:
        if not self._path.is_file():
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить файл",
            str(Path.home() / "Desktop" / self._path.name),
            f"Файлы (*{self._path.suffix});;Все файлы (*.*)",
        )
        if not dest:
            return
        shutil.copy2(self._path, dest)


class _ResultFileBridge(QObject):
    offered = Signal(object, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.offered.connect(self._on_offered, Qt.ConnectionType.QueuedConnection)

    def _on_offered(self, paths: object, workflow_id: str) -> None:
        from app.tools.hitl import attach_feed_widget
        from app.tools.result_files import queue_unattached_result_file

        items = paths if isinstance(paths, list) else []
        for raw in items:
            path = Path(str(raw))
            if not path.is_file():
                continue
            card = ResultFileCard(path)
            if not attach_feed_widget(card, workflow_id):
                queue_unattached_result_file(path, workflow_id)
                card.deleteLater()


def offer_result_files(paths: list[Path], *, workflow_id: str = "") -> None:
    global _bridge
    if _bridge is None:
        _bridge = _ResultFileBridge()
    _bridge.offered.emit([str(path) for path in paths], str(workflow_id or ""))


def flush_pending_result_files() -> None:
    from app.tools.result_files import take_unattached_result_files

    pending = take_unattached_result_files()
    if pending:
        offer_result_files(
            [Path(path) for path, _wid in pending],
            workflow_id=pending[0][1],
        )
