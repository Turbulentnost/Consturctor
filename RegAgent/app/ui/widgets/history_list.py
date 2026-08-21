from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.storage.session_log import preview_text
from app.ui.theme import MAIN_TEXT, app_font


_CARD_QSS = """
QFrame#HistoryTurn {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 12px;
}
QFrame#HistoryTurn:hover {
    background: #EAF7F3;
    border-color: rgba(8,116,95,0.40);
}
"""


class _TurnCard(QFrame):
    clicked = Signal(int)

    def __init__(self, index: int, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self.setObjectName("HistoryTurn")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(_CARD_QSS)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setToolTip("Перейти к этому запросу в диалоге")

        caption = QLabel(f"Запрос {index + 1}")
        caption.setFont(app_font(12, QFont.Weight.DemiBold))
        caption.setStyleSheet("color: #06483D; background: transparent;")

        arrow = QLabel("→")
        arrow.setFont(app_font(14, QFont.Weight.DemiBold))
        arrow.setStyleSheet("color: #08745F; background: transparent;")

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        head.addWidget(caption, 1)
        head.addWidget(arrow, 0)

        body = QLabel(preview_text(text, 220))
        body.setWordWrap(True)
        body.setMinimumWidth(0)
        body.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Minimum)
        body.setFont(app_font(13))
        body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        body.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(6)
        root.addLayout(head)
        root.addWidget(body)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit(self._index)
        super().mouseReleaseEvent(event)


class HistoryList(QScrollArea):
    turn_selected = Signal(int)

    def __init__(self, turns: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(280)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)
        for index, text in enumerate(turns):
            card = _TurnCard(index, text)
            card.clicked.connect(self.turn_selected.emit)
            layout.addWidget(card)
        layout.addStretch(1)
        self.setWidget(host)
