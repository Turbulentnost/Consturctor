from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from app.ui.theme import COLOR_CONTENT_BG

CHAT_BG_GRID = Path(__file__).resolve().parent / "assets" / "bg" / "chat_bg_grid.png"
CHAT_BG_ROBO = Path(__file__).resolve().parents[1] / "ui" / "temp" / "robo2.png"
CHAT_FRAME_RADIUS = 16.0


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


class ChatWallpaper(QWidget):
    """Fixed chat backdrop, clipped to the feed frame."""

    def __init__(
        self,
        parent: QWidget | None = None,
        path: str | Path | None = None,
        radius: float = CHAT_FRAME_RADIUS,
    ) -> None:
        super().__init__(parent)
        self._radius = radius
        self._background = QPixmap(str(path or CHAT_BG_GRID))
        if self._background.isNull():
            self._background = QPixmap(str(CHAT_BG_ROBO))
        if self._background.isNull():
            self._background = QPixmap(str(CHAT_BG_GRID))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = _rounded(QRectF(self.rect()), self._radius)
        painter.setClipPath(clip)
        painter.fillRect(self.rect(), COLOR_CONTENT_BG)
        if self._background.isNull() or self._background.width() < 8:
            painter.end()
            return
        scaled = self._background.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()


class ChatFrameRing(QWidget):
    """Glass edge around the conversation feed."""

    def __init__(self, parent: QWidget | None = None, radius: float = CHAT_FRAME_RADIUS) -> None:
        super().__init__(parent)
        self._radius = radius
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        path = _rounded(rect, self._radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(8, 116, 95, 42), 3.0))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(98, 224, 190, 120), 1.2))
        painter.drawPath(path)
        inner = rect.adjusted(1.2, 1.2, -1.2, -1.2)
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1.0))
        painter.drawPath(_rounded(inner, max(2.0, self._radius - 1.2)))
        painter.end()
