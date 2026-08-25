from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QPushButton,
    QWidget,
)

from app.chat.icons import close_icon
from app.ui.theme import app_font


class FlowLayout(QLayout):
    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item: QLayoutItem) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x = rect.x()
        y = rect.y()
        line_h = 0
        space = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + space
            if next_x - space > rect.right() and line_h > 0:
                x = rect.x()
                y = y + line_h + space
                next_x = x + hint.width() + space
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() if self._items else 0


class FileChip(QFrame):
    removed = Signal(str)

    def __init__(self, path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.path = path
        self.setObjectName("fileChip")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(36)
        self._idle_qss = (
            "QFrame#fileChip { background: rgba(8, 116, 95, 0.62);"
            " border: none; border-radius: 10px; }"
        )
        self._hover_qss = (
            "QFrame#fileChip { background: rgba(8, 116, 95, 1.0);"
            " border: none; border-radius: 10px; }"
        )
        self.setStyleSheet(self._idle_qss)
        name = QLabel(Path(path).name)
        name.setFont(app_font(12))
        name.setStyleSheet("color: #FFFFFF; background: transparent;")
        metrics = name.fontMetrics()
        name.setText(metrics.elidedText(Path(path).name, Qt.TextElideMode.ElideMiddle, 180))
        name.setToolTip(Path(path).name)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 22, 0)
        row.setSpacing(0)
        row.addWidget(name)
        self._close = QPushButton(self)
        self._close.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close.setToolTip("Удалить")
        self._close.setFixedSize(18, 18)
        self._close.setIcon(close_icon(10))
        self._close.setIconSize(QSize(10, 10))
        self._close.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,0.22); border: none; border-radius: 9px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.36); }"
        )
        self._close.hide()
        self._close.clicked.connect(lambda: self.removed.emit(self.path))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._close.move(self.width() - 22, (self.height() - 18) // 2)

    def enterEvent(self, event) -> None:  # noqa: N802
        super().enterEvent(event)
        self.setStyleSheet(self._hover_qss)
        self._close.show()
        self._close.raise_()

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.setStyleSheet(self._idle_qss)
        self._close.hide()
