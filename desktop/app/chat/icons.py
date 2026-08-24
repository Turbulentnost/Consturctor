from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

_CLIP_COLOR = "#08745F"

_SVG_PAPERCLIP = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M21.44 11.05 12.25 20.24a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"
        stroke="{_CLIP_COLOR}" stroke-width="2.35" stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def _dpr() -> float:
    app = QApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def svg_pixmap(svg: str, width: int, height: int) -> QPixmap:
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    scale = _dpr()
    pix = QPixmap(max(1, int(width * scale)), max(1, int(height * scale)))
    pix.setDevicePixelRatio(scale)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, width, height))
    painter.end()
    return pix


def paperclip_icon(size: int = 22) -> QIcon:
    return QIcon(svg_pixmap(_SVG_PAPERCLIP, size, size))


def paperclip_icon_size(size: int = 22) -> QSize:
    return QSize(size, size)


_SVG_CLOSE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" fill="none">
  <path d="M4.2 4.2 11.8 11.8 M11.8 4.2 4.2 11.8" stroke="#FFFFFF" stroke-width="1.9"
        stroke-linecap="round"/>
</svg>"""


def close_icon(size: int = 10) -> QIcon:
    return QIcon(svg_pixmap(_SVG_CLOSE, size, size))


_SVG_AGENT = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="4.2" y="7.2" width="15.6" height="11.2" rx="3.2" stroke="{_CLIP_COLOR}" stroke-width="1.9"/>
  <circle cx="9.2" cy="12.4" r="1.15" fill="{_CLIP_COLOR}"/>
  <circle cx="14.8" cy="12.4" r="1.15" fill="{_CLIP_COLOR}"/>
  <path d="M12 3.6 V7.2 M8.4 4.8 H15.6" stroke="{_CLIP_COLOR}" stroke-width="1.9"
        stroke-linecap="round"/>
</svg>"""


def agent_icon(size: int = 22) -> QIcon:
    return QIcon(svg_pixmap(_SVG_AGENT, size, size))


def agent_icon_size(size: int = 22) -> QSize:
    return QSize(size, size)
