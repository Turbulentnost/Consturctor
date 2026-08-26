from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from app.ui.theme import (
    COLOR_ACTIVE_BG,
    ICON_CHAT,
    MAIN_TEXT,
    SIDEBAR_COLLAPSED,
    SIDEBAR_MIDDLE,
    nerd_font,
)
from app.ui.widgets.sidebar import (
    NAV_BY_KEY,
    NavigationItem,
    _DRAG_THRESHOLD,
    _load_icon_pair,
    start_nav_drag,
)


class DockCircleItem(QWidget):
    clicked = Signal(str)
    drag_started = Signal(str)
    drag_finished = Signal()

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self.item = NAV_BY_KEY[key]
        self._icon_inactive, self._icon_active = _load_icon_pair(self.item.icon)
        self._active = False
        self._pressed = False
        self._dragging = False
        self._press_pos = QPoint()
        self.setFixedSize(48, 48)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(self.item.label)

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self._dragging = False
            self._press_pos = event.position().toPoint()
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pressed and not self._dragging:
            if (event.position().toPoint() - self._press_pos).manhattanLength() >= _DRAG_THRESHOLD:
                self._dragging = True
                self.drag_started.emit(self._key)
                start_nav_drag(self, self.item)
                self.drag_finished.emit()
                self._pressed = False
                self._dragging = False
                self.update()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self._pressed
            and not self._dragging
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.pos())
        ):
            self.clicked.emit(self._key)
        self._pressed = False
        self._dragging = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        fill = COLOR_ACTIVE_BG if self._active else QColor(91, 160, 143, 90)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(self.rect()).adjusted(1, 1, -1, -1))
        icon = self._icon_active if self._active else self._icon_inactive
        if not icon.isNull():
            painter.drawPixmap((self.width() - icon.width()) // 2, (self.height() - icon.height()) // 2, icon)
        else:
            painter.setPen(MAIN_TEXT if self._active else QColor("#FFFFFF"))
            painter.setFont(nerd_font(18))
            painter.drawText(QRectF(self.rect()), int(Qt.AlignmentFlag.AlignCenter), ICON_CHAT)
        painter.end()


class DockRail(QWidget):
    page_changed = Signal(str)
    drag_started = Signal(str)
    drag_finished = Signal()

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._side = side
        self._active_key = ""
        self._buttons: dict[str, QWidget] = {}
        self._horizontal = side in {"top", "bottom"}
        if self._horizontal:
            self.setFixedHeight(72)
            self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            self._box = QHBoxLayout(self)
        else:
            self.setFixedWidth(SIDEBAR_COLLAPSED)
            self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
            self._box = QVBoxLayout(self)
        self._box.setContentsMargins(12, 12, 12, 12)
        self._box.setSpacing(10)
        self._box.addStretch(1)
        self.hide()

    def set_keys(self, keys: list[str]) -> None:
        while self._box.count():
            taken = self._box.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.deleteLater()
        self._buttons.clear()
        if self._horizontal:
            self._box.addStretch(1)
        for key in keys:
            if key not in NAV_BY_KEY:
                continue
            button = self._make_button(key)
            self._box.addWidget(button, 0, Qt.AlignmentFlag.AlignCenter)
            self._buttons[key] = button
        self._box.addStretch(1)
        self.mark_active(self._active_key)
        self.setVisible(bool(keys))

    def mark_active(self, key: str) -> None:
        self._active_key = key
        for item_key, button in self._buttons.items():
            if hasattr(button, "set_active"):
                button.set_active(item_key == key)

    def _make_button(self, key: str) -> QWidget:
        if self._horizontal:
            button = DockCircleItem(key)
            button.clicked.connect(self.page_changed.emit)
            button.drag_started.connect(self.drag_started.emit)
            button.drag_finished.connect(self.drag_finished.emit)
            return button
        item = NAV_BY_KEY[key]
        inactive, active = _load_icon_pair(item.icon)
        button = NavigationItem(item, icon_inactive=inactive, icon_active=active)
        button.set_collapsed(True)
        button.setFixedWidth(SIDEBAR_COLLAPSED - 24)
        button.clicked.connect(self.page_changed.emit)
        button.drag_started.connect(self.drag_started.emit)
        button.drag_finished.connect(self.drag_finished.emit)
        return button

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = self.rect()
        painter.fillRect(rect, SIDEBAR_MIDDLE)
        painter.setPen(QPen(QColor(255, 255, 255, 18), 1))
        if self._horizontal:
            y = rect.bottom() - 0.5 if self._side == "top" else rect.top() + 0.5
            painter.drawLine(rect.left(), y, rect.right(), y)
        else:
            painter.drawLine(rect.left() + 0.5, rect.top(), rect.left() + 0.5, rect.bottom())
        painter.end()
