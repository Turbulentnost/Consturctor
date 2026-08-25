from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from app.ui.theme import COLOR_CONTENT_BG

CHAT_BG_GRID = Path(__file__).resolve().parent / "assets" / "bg" / "chat_bg_grid.png"
CHAT_BG_ROBO = Path(__file__).resolve().parents[1] / "ui" / "temp" / "robo2.png"


class ChatWallpaper(QWidget):
    """Fixed light chat backdrop from robo2.png."""

    def __init__(self, parent: QWidget | None = None, path: str | Path | None = None) -> None:
        super().__init__(parent)
        self._background = QPixmap(str(path or CHAT_BG_ROBO))
        if self._background.isNull():
            self._background = QPixmap(str(CHAT_BG_GRID))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAutoFillBackground(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
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
