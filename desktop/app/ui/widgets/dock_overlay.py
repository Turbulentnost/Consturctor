from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from app.ui.widgets.dock_layout import FLOAT, NAV_MIME, SIDES

_CHECK_A = QColor(160, 160, 160, 110)
_CHECK_B = QColor(220, 220, 220, 80)
_DASH = QColor(70, 70, 70, 210)
_PLUS_BG = QColor(255, 255, 255, 210)
_PLUS = QColor(255, 255, 255, 240)
_HOVER = QColor(8, 116, 95, 40)


class DockDropOverlay(QWidget):
    dropped = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hover = ""
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setAcceptDrops(True)
        self.hide()

    def zone_rects(self) -> dict[str, QRect]:
        width = self.width()
        height = self.height()
        strip_v = max(96, int(width * 0.15))
        strip_h = max(80, int(height * 0.13))
        return {
            "left": QRect(0, 0, strip_v, height),
            "right": QRect(width - strip_v, 0, strip_v, height),
            "top": QRect(strip_v, 0, width - 2 * strip_v, strip_h),
            "bottom": QRect(strip_v, height - strip_h, width - 2 * strip_v, strip_h),
            FLOAT: QRect(strip_v, strip_h, width - 2 * strip_v, height - 2 * strip_h),
        }

    def hit_side(self, pos: QPoint) -> str:
        rects = self.zone_rects()
        for side in SIDES:
            if rects[side].contains(pos):
                return side
        if rects[FLOAT].contains(pos):
            return FLOAT
        return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasFormat(NAV_MIME):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if not event.mimeData().hasFormat(NAV_MIME):
            event.ignore()
            return
        side = self.hit_side(event.position().toPoint())
        if side != self._hover:
            self._hover = side
            self.update()
        if side:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._hover = ""
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        key = bytes(event.mimeData().data(NAV_MIME)).decode("utf-8")
        side = self.hit_side(event.position().toPoint())
        self._hover = ""
        self.update()
        if side in {*SIDES, FLOAT} and key:
            self.dropped.emit(side, key)
            event.acceptProposedAction()
            return
        event.ignore()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for side, rect in self.zone_rects().items():
            self._paint_zone(painter, rect, side == self._hover, floating=side == FLOAT)
        painter.end()

    def _paint_zone(self, painter: QPainter, rect: QRect, hover: bool, *, floating: bool = False) -> None:
        inset = 28 if floating else 6
        path = QPainterPath()
        path.addRoundedRect(QRectF(rect).adjusted(inset, inset, -inset, -inset), 18, 18)
        painter.save()
        painter.setClipPath(path)
        if hover:
            painter.fillPath(path, _HOVER)
        if not floating:
            self._fill_checker(painter, rect)
        painter.restore()
        pen = QPen(_DASH, 3, Qt.PenStyle.DashLine)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        if floating:
            self._paint_float_hint(painter, rect)
        else:
            self._paint_plus(painter, rect)

    def _paint_float_hint(self, painter: QPainter, rect: QRect) -> None:
        center = rect.center()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_PLUS_BG)
        painter.drawRoundedRect(center.x() - 26, center.y() - 34, 52, 40, 8, 8)
        painter.setPen(QPen(QColor("#08745F"), 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(center.x() - 20, center.y() - 22, 40, 22, 4, 4)
        painter.setPen(QColor("#06483D"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        painter.drawText(
            QRect(rect.left(), center.y() + 16, rect.width(), 22),
            int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
            "Отдельное окно",
        )

    def _fill_checker(self, painter: QPainter, rect: QRect) -> None:
        size = 10
        left = rect.left()
        top = rect.top()
        for y in range(top, rect.bottom(), size):
            row = (y - top) // size
            for x in range(left, rect.right(), size):
                col = (x - left) // size
                painter.fillRect(x, y, size, size, _CHECK_A if (row + col) % 2 == 0 else _CHECK_B)

    def _paint_plus(self, painter: QPainter, rect: QRect) -> None:
        center = rect.center()
        radius = 28
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_PLUS_BG)
        painter.drawEllipse(center, radius, radius)
        painter.setPen(QPen(QColor("#08745F"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(center.x() - 12, center.y(), center.x() + 12, center.y())
        painter.drawLine(center.x(), center.y() - 12, center.x(), center.y() + 12)
