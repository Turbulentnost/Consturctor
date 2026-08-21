"""List of simultaneous agent runs from a calendar group."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.api_client import CalendarEvent
from app.ui.theme import app_font
from app.ui.widgets.run_calendar import _STATUS_STYLE, _runs_word, group_heading, parse_iso

_SECONDARY = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #F4F7F6; }
"""
_CARD = """
QFrame#GroupRunCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 14px;
}
QFrame#GroupRunCard:hover {
    background: #F3FAF7;
    border-color: #08745F;
}
"""
_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 10px; padding: 0 14px;
}
QPushButton:hover { background: #0A8670; }
"""


class AgentGroupRunsPage(QWidget):
    back_requested = Signal()
    open_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._events: list[CalendarEvent] = []
        self._title = QLabel("Запуски")
        self._title.setFont(app_font(28, QFont.Weight.DemiBold))
        self._title.setStyleSheet("color: #101817; background: transparent;")
        self._subtitle = QLabel("Одновременные запуски")
        self._subtitle.setFont(app_font(13))
        self._subtitle.setStyleSheet("color: #6B7773; background: transparent;")
        back = QPushButton("Назад")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(36)
        back.setStyleSheet(_SECONDARY)
        back.clicked.connect(self.back_requested.emit)
        head = QHBoxLayout()
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(self._title)
        text.addWidget(self._subtitle)
        head.addLayout(text, 1)
        head.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)

        self._list = QVBoxLayout()
        self._list.setSpacing(8)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner.setLayout(self._list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(head)
        layout.addWidget(scroll, 1)

    def show_group(self, events: list[CalendarEvent]) -> None:
        self._events = [item for item in events if isinstance(item, CalendarEvent)]
        self._title.setText(group_heading(self._events) if self._events else "Запуски")
        self._subtitle.setText(f"{len(self._events)} {_runs_word(len(self._events))}")
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for event in self._events:
            self._list.addWidget(self._row(event))
        self._list.addStretch(1)

    def _row(self, event: CalendarEvent) -> QWidget:
        card = QFrame()
        card.setObjectName("GroupRunCard")
        card.setStyleSheet(_CARD)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        stamp = parse_iso(event.start_at)
        time_text = stamp.strftime("%H:%M") if stamp else ""
        _bg, color, label = _STATUS_STYLE.get(event.status, _STATUS_STYLE["scheduled"])
        title = QLabel(event.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent; border: none;")
        meta = QLabel(f"{time_text}  ·  {label}")
        meta.setFont(app_font(12))
        meta.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        detail = QLabel(event.subtitle or "")
        detail.setFont(app_font(12))
        detail.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        detail.setWordWrap(True)
        open_btn = QPushButton("Открыть")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setFixedHeight(34)
        open_btn.setStyleSheet(_PRIMARY)
        open_btn.clicked.connect(
            lambda _=False, item=event: self.open_requested.emit(item.workflow_id, item.run_id or "")
        )
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(title)
        text.addWidget(meta)
        if event.subtitle:
            text.addWidget(detail)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        row.addLayout(text, 1)
        row.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        card.mousePressEvent = (  # type: ignore[method-assign]
            lambda ev, item=event: self.open_requested.emit(item.workflow_id, item.run_id or "")
        )
        return card
