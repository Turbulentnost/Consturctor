from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.ui.theme import (
    COLOR_ACTIVE_BG,
    COLOR_ACTIVE_FG,
    MINT,
    MINT_SOFT,
    NAV_ITEM_HEIGHT,
    NAV_ITEM_RADIUS,
    SIDEBAR_BOTTOM,
    SIDEBAR_COLLAPSED,
    SIDEBAR_EXPANDED,
    SIDEBAR_MIDDLE,
    SIDEBAR_PADDING_X,
    SIDEBAR_TOP,
    TEXT_LIGHT,
    TEXT_MUTED,
    app_font,
)

INACTIVE_PILL = QColor(91, 160, 143, 72)
INACTIVE_HOVER = QColor(112, 190, 169, 96)
INACTIVE_PRESSED = QColor(55, 120, 103, 120)
ITEM_GAP = 8


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str


class NavigationItem(QWidget):
    clicked = Signal(str)

    def __init__(self, item: NavItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = item
        self._active = False
        self._hover = False
        self._pressed = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(NAV_ITEM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_active(self, active: bool) -> None:
        if self._active == active:
            return
        self._active = active
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._pressed = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if (
            self._pressed
            and event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.pos())
        ):
            self.clicked.emit(self.item.key)
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0, 1, 0, -1), NAV_ITEM_RADIUS, NAV_ITEM_RADIUS)

        if self._active:
            fill = COLOR_ACTIVE_BG
            text = COLOR_ACTIVE_FG
        elif self._pressed:
            fill = INACTIVE_PRESSED
            text = TEXT_LIGHT
        elif self._hover:
            fill = INACTIVE_HOVER
            text = TEXT_LIGHT
        else:
            fill = INACTIVE_PILL
            text = TEXT_MUTED

        p.fillPath(path, fill)
        self._draw_icon(p, rect.left() + 18, rect.center().y(), text)
        p.setPen(text)
        p.setFont(app_font(14, QFont.Weight.Medium if not self._active else QFont.Weight.DemiBold))
        p.drawText(
            QRectF(rect.left() + 44, rect.top(), rect.width() - 52, rect.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.item.label,
        )
        p.end()

    def _draw_icon(self, p: QPainter, cx: float, cy: float, color: QColor) -> None:
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        kind = self.item.icon
        if kind == "plus":
            p.drawLine(int(cx - 6), int(cy), int(cx + 6), int(cy))
            p.drawLine(int(cx), int(cy - 6), int(cx), int(cy + 6))
        else:
            p.drawEllipse(QRectF(cx - 8, cy - 4, 8, 8))
            p.drawEllipse(QRectF(cx + 2, cy - 3, 7, 7))
            p.drawArc(int(cx - 10), int(cy + 1), 13, 9, 0, 180 * 16)
            p.drawArc(int(cx), int(cy + 2), 12, 8, 0, 180 * 16)


class GlassSidebar(QWidget):
    page_changed = Signal(str)
    collapse_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = [
            NavItem("workflow", "Конструктор", "plus"),
            NavItem("saved", "Мои workflow", "agents"),
        ]
        self._active_key = "workflow"
        self._collapsed = False
        self._buttons: dict[str, NavigationItem] = {}
        self.setFixedWidth(SIDEBAR_EXPANDED)
        self.setMinimumWidth(200)
        self.setMinimumHeight(400)
        self._build_layout()
        self.set_active_key("workflow", animate=False)

    def set_active_key(self, key: str, *, animate: bool = True) -> None:
        del animate  # reserved for future motion
        if key not in self._buttons:
            return
        self._active_key = key
        for item_key, button in self._buttons.items():
            button.set_active(item_key == key)
        self.page_changed.emit(key)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(SIDEBAR_EXPANDED if not self._collapsed else SIDEBAR_COLLAPSED, 600)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self.setFixedWidth(SIDEBAR_COLLAPSED if self._collapsed else SIDEBAR_EXPANDED)
        self.collapse_toggled.emit(self._collapsed)
        self.update()

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(SIDEBAR_PADDING_X, 22, SIDEBAR_PADDING_X, 22)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 12, 0)
        header.setSpacing(11)

        mark = QLabel("C")
        mark.setFixedSize(36, 36)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFont(app_font(16, QFont.Weight.Bold))
        mark.setStyleSheet(
            """
            color: #06483D;
            background: #F7FBFA;
            border-radius: 18px;
            """
        )
        header.addWidget(mark)

        title = QLabel("Cursor Constructor")
        title.setFont(app_font(14, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #EAF7F3; background: transparent;")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        header.addWidget(title, 1)

        collapse = QPushButton("‹")
        collapse.setFixedSize(28, 28)
        collapse.setCursor(Qt.CursorShape.PointingHandCursor)
        collapse.setStyleSheet(
            """
            QPushButton {
                color: #EAF7F3;
                background: rgba(255,255,255,0.10);
                border: 1px solid rgba(255,255,255,0.14);
                border-radius: 14px;
                font-size: 18px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.16); }
            """
        )
        collapse.clicked.connect(self._toggle_collapse)
        header.addWidget(collapse)

        root.addLayout(header)
        root.addSpacing(22)

        nav = QVBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(ITEM_GAP)
        for item in self._items:
            button = NavigationItem(item)
            button.clicked.connect(self.set_active_key)
            nav.addWidget(button)
            self._buttons[item.key] = button
        root.addLayout(nav)
        root.addStretch(1)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        gradient = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        gradient.setColorAt(0.0, SIDEBAR_TOP)
        gradient.setColorAt(0.45, SIDEBAR_MIDDLE)
        gradient.setColorAt(1.0, SIDEBAR_BOTTOM)
        p.fillRect(rect, gradient)

        glow = QRadialGradient(rect.left() + 56, rect.top() + 70, 145)
        glow.setColorAt(0.0, MINT_SOFT)
        glow.setColorAt(1.0, QColor(98, 224, 190, 0))
        p.fillRect(rect, glow)

        p.setPen(QPen(QColor(MINT.red(), MINT.green(), MINT.blue(), 34), 1))
        p.drawLine(rect.right() - 0.5, rect.top() + 18, rect.right() - 0.5, rect.bottom() - 18)
        p.end()
