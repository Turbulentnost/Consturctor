from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.theme import COLOR_CONTENT_BG, SIDEBAR_MIDDLE, app_font
from app.ui.widgets.sidebar import NAV_BY_KEY, circle_ghost, start_nav_drag

_CLOSE = """
QPushButton {
    background: transparent;
    color: #EAF7F3;
    border: none;
    border-radius: 12px;
    font-size: 16px;
}
QPushButton:hover { background: rgba(255,255,255,0.14); }
"""


class _DragHandle(QWidget):
    drag_started = Signal(str)
    drag_finished = Signal()

    def __init__(self, key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._press = QPoint()
        self._dragging = False
        self.setFixedSize(36, 36)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        item = NAV_BY_KEY[key]
        self._ghost = circle_ghost(item, 36)
        self.setToolTip("Перетащите на панель, чтобы вернуть вкладку")

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.buttons() & Qt.MouseButton.LeftButton and not self._dragging:
            if (event.position().toPoint() - self._press).manhattanLength() >= 8:
                self._dragging = True
                item = NAV_BY_KEY[self._key]
                self.drag_started.emit(self._key)
                start_nav_drag(self, item)
                self.drag_finished.emit()
                self._dragging = False
        super().mouseMoveEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPixmap(0, 0, self._ghost)
        painter.end()


class DetachedTabWindow(QWidget):
    closed = Signal(str)
    moved_or_resized = Signal(str, int, int, int, int)
    drag_started = Signal(str)
    drag_finished = Signal()

    def __init__(self, key: str, page: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._page = page
        item = NAV_BY_KEY[key]
        self.setWindowTitle(item.label)
        self.setObjectName("DetachedTabWindow")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setMinimumSize(720, 520)
        self.resize(1100, 720)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)

        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet(f"background: {SIDEBAR_MIDDLE.name()};")
        title = QLabel(item.label)
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #EAF7F3; background: transparent;")
        hint = QLabel("Перетащите кружок на панель или закройте окно, чтобы вернуть вкладку")
        hint.setFont(app_font(11))
        hint.setStyleSheet("color: rgba(234,247,243,0.62); background: transparent;")
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(32, 32)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(_CLOSE)
        close_btn.setToolTip("Вернуть во вкладки")
        close_btn.clicked.connect(self.close)
        handle = _DragHandle(key)
        handle.drag_started.connect(self.drag_started.emit)
        handle.drag_finished.connect(self.drag_finished.emit)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(title)
        text.addWidget(hint)

        head = QHBoxLayout(header)
        head.setContentsMargins(14, 8, 12, 8)
        head.setSpacing(10)
        head.addWidget(handle, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addLayout(text, 1)
        head.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        page.hide()
        page.setParent(self)
        page.show()

        body = QWidget()
        body.setStyleSheet(f"background: {COLOR_CONTENT_BG.name()};")
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(24, 20, 24, 20)
        body_lay.addWidget(page, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(header)
        root.addWidget(body, 1)

    @property
    def key(self) -> str:
        return self._key

    @property
    def page(self) -> QWidget:
        return self._page

    def release_page(self) -> QWidget:
        page = self._page
        page.hide()
        page.setParent(None)
        return page

    def closeEvent(self, event) -> None:  # noqa: N802
        self._emit_geom()
        self.closed.emit(self._key)
        event.accept()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._emit_geom()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._emit_geom()

    def _emit_geom(self) -> None:
        if not self.isVisible():
            return
        geo = self.geometry()
        self.moved_or_resized.emit(self._key, geo.x(), geo.y(), geo.width(), geo.height())
