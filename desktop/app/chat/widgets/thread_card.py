from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QMenu, QSizePolicy, QVBoxLayout

from app.chat.icons import pin_icon, pin_icon_size
from app.chat.models import ChatThread
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


def _clock(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%H:%M")
    except ValueError:
        return value[11:16] if len(value) >= 16 else value


def _snippet(text: str) -> str:
    return " ".join((text or "").split())


class _Elide(QLabel):
    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._full = text
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self._elide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(0, self.width() - 2)
        if width <= 8:
            super().setText(self._full)
            return
        super().setText(QFontMetrics(self.font()).elidedText(self._full, Qt.TextElideMode.ElideRight, width))


class ThreadCard(QFrame):
    clicked = Signal(str)
    pin_toggled = Signal(str)

    def __init__(self, thread: ChatThread, *, selected: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.thread_id = thread.id
        self._pinned = thread.pinned
        self._unread = thread.unread
        self.setObjectName("threadCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._open_menu)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            QFrame#threadCard {
                background: #FFFFFF;
                border: 1px solid rgba(6, 72, 61, 0.10);
                border-radius: 14px;
            }
            QFrame#threadCard[selected="true"] {
                background: #E7F3EE;
                border: 1px solid rgba(8, 116, 95, 0.28);
            }
            QFrame#threadCard[unread="true"] {
                background: #D4F0E6;
                border: 1px solid rgba(8, 116, 95, 0.42);
            }
            QFrame#threadCard[unread="true"][selected="true"] {
                background: #C5E9D9;
                border: 1px solid rgba(8, 116, 95, 0.50);
            }
            """
        )
        self.set_selected(selected)
        self.setProperty("unread", thread.unread > 0)

        title = _Elide(thread.title or "Диалог")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        title.setWordWrap(False)
        title.setMinimumWidth(0)
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if thread.unread:
            title.setStyleSheet(
                "color: #06483D; background: transparent; border: none; font-weight: 700;"
            )

        pin = QLabel()
        pin.setPixmap(pin_icon(16).pixmap(pin_icon_size(16)))
        pin.setStyleSheet("background: transparent; border: none;")
        pin.setToolTip("Закреплён")
        pin.setVisible(thread.pinned)

        time_lbl = QLabel(_clock(thread.last_message_at))
        time_lbl.setFont(app_font(11, QFont.Weight.DemiBold if thread.unread else QFont.Weight.Normal))
        time_lbl.setStyleSheet(
            f"color: {'#08745F' if thread.unread else COLOR_CONTENT_MUTED.name()};"
            " background: transparent; border: none;"
        )
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(title, 1)
        top.addWidget(pin, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(time_lbl, 0)

        preview = _Elide(_snippet(thread.preview) or "Нет сообщений")
        preview.setFont(app_font(12, QFont.Weight.DemiBold if thread.unread else QFont.Weight.Normal))
        preview.setStyleSheet(
            f"color: {'#06483D' if thread.unread else COLOR_CONTENT_MUTED.name()};"
            " background: transparent; border: none;"
        )
        preview.setWordWrap(False)
        preview.setMinimumWidth(0)
        preview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        preview.setMaximumHeight(20)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(4)
        root.addLayout(top)
        root.addWidget(preview)
        self._refresh_state()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self._refresh_state()

    def set_unread(self, unread: int) -> None:
        self._unread = unread
        self._refresh_state()

    def _refresh_state(self) -> None:
        self.setProperty("unread", self._unread > 0)
        style = self.style()
        style.unpolish(self)
        style.polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.thread_id)
        super().mousePressEvent(event)

    def _open_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setFont(app_font(13))
        menu.setStyleSheet(
            """
            QMenu {
                background: #FAFCFB;
                color: #101817;
                border: 1px solid rgba(16,24,23,0.12);
                border-radius: 12px;
                padding: 6px;
            }
            QMenu::item {
                padding: 8px 18px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background: #E7F3EE;
            }
            """
        )
        action = menu.addAction("Открепить" if self._pinned else "Закрепить")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is action:
            self.pin_toggled.emit(self.thread_id)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(200, 72)
