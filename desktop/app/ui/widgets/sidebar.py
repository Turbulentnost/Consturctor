from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import (
    Property,
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from app.ui.theme import (
    COLOR_ACTIVE_BG,
    COLOR_ACTIVE_FG,
    COLOR_TEXT,
    COLOR_TEXT_MUTED,
    NAV_ITEM_HEIGHT,
    NAV_ITEM_RADIUS,
    SIDEBAR_COLLAPSED,
    SIDEBAR_EXPANDED,
    app_font,
)

# Active tab is a white pill that flows directly into the white content pane.
OVERLAP = 0.0
SCOOP = 0.0
ITEM_GAP = 8.0
SIDEBAR_GREEN = QColor("#073f31")
SIDEBAR_GREEN_DEEP = QColor("#04231d")
INACTIVE_PILL = QColor(255, 255, 255, 18)


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str  # plus | agents | kpi


def active_tab_path(
    left: float,
    top: float,
    right: float,
    height: float,
    left_radius: float,
    scoop: float,
) -> QPainterPath:
    """White tab: rounded on the left, softly rounded into the content on the right."""
    r = min(left_radius, height / 2.0)
    rr = min(18.0, height / 2.0)
    bottom = top + height

    path = QPainterPath()
    path.moveTo(left + r, top)
    path.lineTo(right - rr, top)
    path.quadTo(right, top, right, top + rr)
    path.lineTo(right, bottom - rr)
    path.quadTo(right, bottom, right - rr, bottom)
    path.lineTo(left + r, bottom)
    path.arcTo(QRectF(left, bottom - 2 * r, 2 * r, 2 * r), 270, -90)
    path.lineTo(left, top + r)
    path.arcTo(QRectF(left, top, 2 * r, 2 * r), 180, -90)
    path.closeSubpath()
    return path


class GlassSidebar(QWidget):
    """Left nav: active white tab overlaps neighbors and merges into content."""

    page_changed = Signal(str)
    collapse_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = [
            NavItem("create", "Создать агента", "plus"),
            NavItem("agents", "Мои агенты", "agents"),
            NavItem("kpi", "KPI", "kpi"),
        ]
        self._active = 0
        self._collapsed = False
        self._indicator_y = 0.0
        self._hover_index = -1
        self._anim = QPropertyAnimation(self, b"indicatorY", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setMouseTracking(True)
        self.setFixedWidth(SIDEBAR_EXPANDED)
        self.setMinimumHeight(400)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        logo_path = Path(__file__).resolve().parents[1] / "temp" / "logo.png"
        self._logo = QPixmap(str(logo_path)) if logo_path.exists() else QPixmap()

    def items(self) -> list[NavItem]:
        return list(self._items)

    def active_key(self) -> str:
        return self._items[self._active].key

    def set_active_key(self, key: str, *, animate: bool = True) -> None:
        for i, item in enumerate(self._items):
            if item.key == key:
                self._set_active(i, animate=animate)
                return

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _item_top(self, index: int) -> float:
        return 104.0 + index * (NAV_ITEM_HEIGHT + ITEM_GAP)

    def _tab_top(self) -> float:
        return self._indicator_y - OVERLAP

    def _tab_height(self) -> float:
        return float(NAV_ITEM_HEIGHT) + 2 * OVERLAP

    def get_indicator_y(self) -> float:
        return self._indicator_y

    def set_indicator_y(self, value: float) -> None:
        self._indicator_y = value
        self.update()

    indicatorY = Property(float, get_indicator_y, set_indicator_y)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._indicator_y = self._item_top(self._active)
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._anim.state() != QAbstractAnimation.State.Running:
            self._indicator_y = self._item_top(self._active)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(SIDEBAR_EXPANDED if not self._collapsed else SIDEBAR_COLLAPSED, 600)

    def _set_active(self, index: int, *, animate: bool = True) -> None:
        if index < 0 or index >= len(self._items):
            return
        self._active = index
        target = self._item_top(index)
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self._indicator_y)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._indicator_y = target
            self.update()
        self.page_changed.emit(self._items[index].key)

    def _toggle_collapse(self) -> None:
        self._collapsed = not self._collapsed
        self.setFixedWidth(SIDEBAR_COLLAPSED if self._collapsed else SIDEBAR_EXPANDED)
        self.collapse_toggled.emit(self._collapsed)
        self.update()

    def _hit_nav(self, pos: QPoint) -> int:
        x0 = 10
        x1 = self.width()
        for i in range(len(self._items)):
            y = int(self._item_top(i))
            # Hit the nominal row (not only the overlapping white)
            if x0 <= pos.x() <= x1 and y <= pos.y() <= y + NAV_ITEM_HEIGHT:
                return i
        return -1

    def _hit_collapse(self, pos: QPoint) -> bool:
        cx, cy, r = self.width() - 18, 38, 11
        dx, dy = pos.x() - cx, pos.y() - cy
        return dx * dx + dy * dy <= r * r

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        idx = self._hit_nav(event.position().toPoint())
        if idx != self._hover_index:
            self._hover_index = idx
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover_index = -1
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if self._hit_collapse(pos):
            self._toggle_collapse()
            return
        idx = self._hit_nav(pos)
        if idx >= 0 and idx != self._active:
            self._set_active(idx, animate=True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = float(self.width())
        h = float(self.height())

        p.fillRect(QRectF(0, 0, w, h), QColor(0, 0, 0, 0))

        left = 6.0
        # Inactive pills stay inside the sidebar; active tab reaches the white pane.
        inactive_right = w - 12
        inactive_w = max(80.0, inactive_right - left)

        for i, _item in enumerate(self._items):
            if i == self._active:
                continue
            y = self._item_top(i)
            pill = QRectF(left, y, inactive_w, float(NAV_ITEM_HEIGHT))
            path = QPainterPath()
            path.addRoundedRect(pill, float(NAV_ITEM_RADIUS), float(NAV_ITEM_RADIUS))
            fill = QColor(255, 255, 255, 32) if i == self._hover_index else INACTIVE_PILL
            p.fillPath(path, fill)

        # Active on top — white tab flushes into content, no green cutouts.
        tab_top = self._tab_top()
        tab_h = self._tab_height()
        tab = active_tab_path(
            left=left,
            top=tab_top,
            right=w,
            height=tab_h,
            left_radius=float(NAV_ITEM_RADIUS) + OVERLAP * 0.35,
            scoop=SCOOP,
        )
        p.fillPath(tab, COLOR_ACTIVE_BG)

        self._draw_logo(p)
        self._draw_collapse(p)

        for i, item in enumerate(self._items):
            active = i == self._active
            y = self._item_top(i)
            color = COLOR_ACTIVE_FG if active else COLOR_TEXT_MUTED
            if not active and i == self._hover_index:
                color = COLOR_TEXT
            self._draw_item(p, item, y, color, active)

        p.end()

    def _draw_logo(self, p: QPainter) -> None:
        cx, cy, r = 26, 38, 14
        p.setPen(Qt.PenStyle.NoPen)
        if not self._logo.isNull():
            p.drawPixmap(
                int(cx - r),
                int(cy - r),
                r * 2,
                r * 2,
                self._logo,
            )
        else:
            p.setBrush(QColor(255, 255, 255, 230))
            p.drawEllipse(QPoint(cx, cy), r, r)
            p.setBrush(SIDEBAR_GREEN_DEEP)
            leaf = QPainterPath()
            leaf.moveTo(cx, cy - 8)
            leaf.cubicTo(cx + 10, cy - 4, cx + 10, cy + 8, cx, cy + 10)
            leaf.cubicTo(cx - 10, cy + 8, cx - 10, cy - 4, cx, cy - 8)
            p.drawPath(leaf)
        if not self._collapsed:
            p.setPen(COLOR_TEXT)
            p.setFont(app_font(15, QFont.Weight.DemiBold))
            p.setFont(app_font(13, QFont.Weight.DemiBold))
            p.drawText(QRectF(46, 25, 82, 26), Qt.AlignmentFlag.AlignVCenter, "turbobot")

    def _draw_collapse(self, p: QPainter) -> None:
        cx, cy, r = self.width() - 18, 38, 10
        p.setPen(QPen(QColor(255, 255, 255, 50), 1))
        p.setBrush(QColor(255, 255, 255, 22))
        p.drawEllipse(QPoint(cx, cy), r, r)
        p.setPen(QPen(COLOR_TEXT, 2))
        if self._collapsed:
            p.drawLine(cx - 2, cy - 4, cx + 2, cy)
            p.drawLine(cx + 2, cy, cx - 2, cy + 4)
        else:
            p.drawLine(cx + 2, cy - 4, cx - 2, cy)
            p.drawLine(cx - 2, cy, cx + 2, cy + 4)

    def _draw_item(self, p: QPainter, item: NavItem, y: float, color: QColor, active: bool) -> None:
        icon_x = 22
        icon_y = y + NAV_ITEM_HEIGHT / 2
        self._draw_icon(p, item.icon, icon_x, icon_y, color)
        if self._collapsed:
            return
        p.setPen(color)
        weight = QFont.Weight.DemiBold if active else QFont.Weight.Medium
        p.setFont(app_font(11, weight))
        text_rect = QRectF(40, y, self.width() - 46, NAV_ITEM_HEIGHT)
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, item.label)

    def _draw_icon(self, p: QPainter, kind: str, cx: float, cy: float, color: QColor) -> None:
        pen = QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        if kind == "plus":
            p.drawLine(QPoint(int(cx - 5), int(cy)), QPoint(int(cx + 5), int(cy)))
            p.drawLine(QPoint(int(cx), int(cy - 5)), QPoint(int(cx), int(cy + 5)))
        elif kind == "agents":
            p.drawEllipse(QPoint(int(cx - 4), int(cy - 3)), 4, 4)
            p.drawEllipse(QPoint(int(cx + 5), int(cy - 1)), 3, 3)
            p.drawArc(int(cx - 10), int(cy), 12, 10, 0, 180 * 16)
            p.drawArc(int(cx), int(cy + 2), 10, 8, 0, 180 * 16)
        else:
            p.drawLine(QPoint(int(cx - 7), int(cy + 6)), QPoint(int(cx - 7), int(cy - 2)))
            p.drawLine(QPoint(int(cx), int(cy + 6)), QPoint(int(cx), int(cy - 6)))
            p.drawLine(QPoint(int(cx + 7), int(cy + 6)), QPoint(int(cx + 7), int(cy + 1)))
