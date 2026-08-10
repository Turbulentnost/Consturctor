from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
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

SIDEBAR_GREEN = SIDEBAR_MIDDLE
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
        if self._pressed and event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit(self.item.key)
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
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
        # Integer text box keeps glyphs on the pixel grid (less blur than QRectF).
        p.setPen(text)
        p.setFont(app_font(14, QFont.Weight.Medium if not self._active else QFont.Weight.DemiBold))
        text_rect = self.rect().adjusted(44, 0, -12, 0)
        p.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
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
        elif kind == "home":
            # Roof
            p.drawLine(int(cx - 8), int(cy - 1), int(cx), int(cy - 8))
            p.drawLine(int(cx), int(cy - 8), int(cx + 8), int(cy - 1))
            # House body
            p.drawRect(int(cx - 6), int(cy - 1), 12, 9)
            # Door
            p.drawLine(int(cx - 1.5), int(cy + 8), int(cx - 1.5), int(cy + 2))
            p.drawLine(int(cx + 1.5), int(cy + 8), int(cx + 1.5), int(cy + 2))
            p.drawLine(int(cx - 1.5), int(cy + 2), int(cx + 1.5), int(cy + 2))
        else:
            p.drawLine(int(cx - 7), int(cy + 7), int(cx - 7), int(cy - 1))
            p.drawLine(int(cx), int(cy + 7), int(cx), int(cy - 7))
            p.drawLine(int(cx + 7), int(cy + 7), int(cx + 7), int(cy + 2))


class GlassSidebar(QWidget):
    page_changed = Signal(str)
    collapse_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = [
            NavItem("create", "Создать", "plus"),
            NavItem("agents", "Мои агенты", "home"),
            NavItem("kpi", "KPI", "kpi"),
        ]
        self._active_key = "create"
        self._collapsed = False
        self._buttons: dict[str, NavigationItem] = {}
        self.setFixedWidth(SIDEBAR_EXPANDED)
        self.setMinimumWidth(200)
        self.setMinimumHeight(400)
        logo_path = Path(__file__).resolve().parents[1] / "temp" / "logo.png"
        self._logo = QPixmap(str(logo_path)) if logo_path.exists() else QPixmap()
        self._build_layout()
        self.set_active_key("create", animate=False)

    def items(self) -> list[NavItem]:
        return list(self._items)

    def active_key(self) -> str:
        return self._active_key

    def set_active_key(self, key: str, *, animate: bool = True) -> None:
        if key not in self._buttons:
            return
        self._active_key = key
        for item_key, button in self._buttons.items():
            button.set_active(item_key == key)
        self.page_changed.emit(key)

    def is_collapsed(self) -> bool:
        return self._collapsed

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
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(12)

        logo = QLabel()
        logo.setFixedSize(36, 36)
        logo.setScaledContents(False)
        if not self._logo.isNull():
            logo.setPixmap(
                self._logo.scaled(
                    36,
                    36,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        header.addWidget(logo)

        title = QLabel("turbobot")
        title.setFont(app_font(18, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #EAF7F3; background: transparent;")
        title.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        title.setMinimumWidth(110)
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
