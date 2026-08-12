from __future__ import annotations

import random

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QWidget

from app.ui.theme import COLOR_BG_BOTTOM, COLOR_BG_MID, COLOR_BG_TOP


class GradientBackground(QWidget):
    """Full-bleed emerald→black gradient with subtle grain."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cache: QPixmap | None = None
        self._cache_size = (0, 0)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._cache = None
        super().resizeEvent(event)

    def _build_cache(self, w: int, h: int) -> QPixmap:
        pm = QPixmap(w, h)
        pm.fill(Qt.GlobalColor.black)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, COLOR_BG_TOP)
        grad.setColorAt(0.45, COLOR_BG_MID)
        grad.setColorAt(1.0, COLOR_BG_BOTTOM)
        p.fillRect(0, 0, w, h, grad)

        # Soft glow near top
        glow = QLinearGradient(0, 0, 0, h * 0.55)
        glow.setColorAt(0.0, QColor(40, 140, 100, 70))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, int(h * 0.55), glow)

        rng = random.Random(42)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(max(400, w * h // 2500)):
            x = rng.randint(0, w - 1)
            y = rng.randint(0, h - 1)
            a = rng.randint(8, 28)
            p.setBrush(QColor(255, 255, 255, a))
            p.drawRect(x, y, 1, 1)

        p.end()
        return pm

    def paintEvent(self, _event) -> None:  # noqa: N802
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        if self._cache is None or self._cache_size != (w, h):
            self._cache = self._build_cache(w, h)
            self._cache_size = (w, h)
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._cache)


class GlassPanel(QWidget):
    """Semi-transparent rounded glass card."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        radius: int = 24,
        fill: QColor | None = None,
    ) -> None:
        super().__init__(parent)
        self._radius = radius
        self._fill = fill or QColor(10, 74, 56, 150)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        p.fillPath(path, self._fill)
        p.setPen(QColor(255, 255, 255, 30))
        p.drawPath(path)
        p.end()
