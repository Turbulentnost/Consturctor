from __future__ import annotations

from datetime import datetime

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

from app.api_client import InboxNotification
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


_USER_MENU_RESERVE = 360

_CARD = """
QFrame#NotifyCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 14px;
}
QFrame#NotifyCard[unread="true"] {
    background: #E8F3FB;
    border: 1px solid #B7D4E8;
}
"""
_GONE_CARD = """
QFrame#NotifyCard {
    background: #E6E9E8;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 14px;
}
"""
_SECONDARY = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px; padding: 0 14px;
}
QPushButton:hover { background: #F4F7F6; }
"""


class NotificationsPage(QWidget):
    open_workflow_requested = Signal(str)
    mark_all_requested = Signal()
    clear_requested = Signal()
    item_opened = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel("Уведомления")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._empty = QLabel("Пока нет уведомлений. Когда агент вызовет notify.send, они появятся здесь и на компьютере.")
        self._empty.setWordWrap(True)
        self._empty.setFont(app_font(13))
        self._empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._mark_all = QPushButton("Прочитать все")
        self._mark_all.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mark_all.setFixedHeight(36)
        self._mark_all.setStyleSheet(_SECONDARY)
        self._mark_all.clicked.connect(self.mark_all_requested.emit)
        self._mark_all.hide()
        self._clear = QPushButton("Очистить уведомления")
        self._clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear.setFixedHeight(36)
        self._clear.setStyleSheet(_SECONDARY)
        self._clear.clicked.connect(self.clear_requested.emit)
        self._clear.hide()

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, _USER_MENU_RESERVE, 0)
        header.setSpacing(16)
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._mark_all, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._clear, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)

        self._list = QVBoxLayout()
        self._list.setSpacing(10)
        self._list.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.addLayout(self._list)
        inner_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(self._empty)
        root.addWidget(scroll, 1)

    def set_items(self, items: list[InboxNotification]) -> None:
        while self._list.count():
            taken = self._list.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.deleteLater()
        self._empty.setVisible(not items)
        self._mark_all.setVisible(any(item.unread for item in items))
        self._clear.setVisible(bool(items))
        for item in items:
            self._list.addWidget(self._card(item))

    def _card(self, item: InboxNotification) -> QFrame:
        gone = bool(item.agent_deleted)
        card = QFrame()
        card.setObjectName("NotifyCard")
        card.setProperty("unread", "true" if item.unread and not gone else "false")
        card.setStyleSheet(_GONE_CARD if gone else _CARD)
        card.setCursor(
            Qt.CursorShape.PointingHandCursor
            if item.workflow_id and not gone
            else Qt.CursorShape.ArrowCursor
        )
        title = QLabel(item.title)
        title.setFont(app_font(15, QFont.Weight.DemiBold))
        title.setWordWrap(True)
        title.setStyleSheet(
            "color: #7A8682; background: transparent;"
            if gone
            else f"color: {MAIN_TEXT.name()}; background: transparent;"
        )
        body = QLabel(item.body or "—")
        body.setFont(app_font(13))
        body.setWordWrap(True)
        body.setStyleSheet(
            "color: #8A9692; background: transparent;"
            if gone
            else f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;"
        )
        meta = QLabel(_meta_line(item))
        meta.setFont(app_font(11))
        meta.setStyleSheet("color: #8A9692; background: transparent;" if gone else "color: #6B7773; background: transparent;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        lay.addWidget(title)
        lay.addWidget(body)
        lay.addWidget(meta)
        card.mousePressEvent = lambda event, nid=item.id, wid=item.workflow_id, dead=gone: self._on_click(  # type: ignore[method-assign]
            event, nid, wid, dead
        )
        return card

    def _on_click(self, event, notification_id: str, workflow_id: str, agent_deleted: bool = False) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.item_opened.emit(notification_id)
        if agent_deleted:
            return
        if (workflow_id or "").strip():
            self.open_workflow_requested.emit(workflow_id)


def _meta_line(item: InboxNotification) -> str:
    parts: list[str] = []
    if item.sender_fio:
        parts.append(item.sender_fio)
    stamp = _pretty_time(item.created_at or item.send_at)
    if stamp:
        parts.append(stamp)
    if item.agent_deleted:
        parts.append("агент удалён")
    elif item.unread:
        parts.append("новое")
    return " · ".join(parts)


def _pretty_time(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:16]
    return parsed.astimezone().strftime("%d.%m.%Y %H:%M")
