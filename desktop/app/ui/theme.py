from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPainterPath, QPixmap

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

# Emerald glass palette (target)
SIDEBAR_TOP = QColor("#08745F")
SIDEBAR_MIDDLE = QColor("#06483D")
SIDEBAR_BOTTOM = QColor("#011713")
MINT = QColor("#62E0BE")
MINT_SOFT = QColor(98, 224, 190, 70)
WHITE = QColor("#F7FBFA")
TEXT_LIGHT = QColor("#EAF7F3")
TEXT_MUTED = QColor("#A8C8BF")
MAIN_TEXT = QColor("#101817")

COLOR_BG_TOP = SIDEBAR_TOP
COLOR_BG_MID = SIDEBAR_MIDDLE
COLOR_BG_BOTTOM = SIDEBAR_BOTTOM
COLOR_GLASS = QColor(6, 72, 61, 150)
COLOR_GLASS_BORDER = QColor(98, 224, 190, 38)
COLOR_TEXT = TEXT_LIGHT
COLOR_TEXT_MUTED = TEXT_MUTED
COLOR_ACTIVE_BG = WHITE
COLOR_ACTIVE_FG = MAIN_TEXT
COLOR_ACCENT_ERROR = QColor("#ff8a80")
COLOR_CONTENT_BG = QColor("#FAFCFB")
COLOR_CONTENT_TEXT = MAIN_TEXT
COLOR_CONTENT_MUTED = QColor("#6B7773")

SIDEBAR_EXPANDED = 268
SIDEBAR_COLLAPSED = 84
NAV_ITEM_HEIGHT = 44
NAV_ITEM_RADIUS = 16
SIDEBAR_PADDING_X = 18
CONTENT_PADDING_X = 36
CONTENT_PADDING_TOP = 30

FONT_FAMILY = "Manrope"

_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def load_fonts() -> str:
    """Load bundled Manrope static faces; return family name to use."""
    global FONT_FAMILY
    preferred: list[str] = []
    # Prefer complete static TTFs — variable/broken faces look soft on Windows.
    for name in (
        "Manrope-Regular.ttf",
        "Manrope-Medium.ttf",
        "Manrope-SemiBold.ttf",
        "Manrope-Bold.ttf",
        "Manrope-Variable.ttf",
    ):
        path = _ASSETS / name
        if not path.exists():
            continue
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            continue
        preferred.extend(QFontDatabase.applicationFontFamilies(font_id))

    for candidate in preferred:
        if candidate == "Manrope":
            FONT_FAMILY = candidate
            return FONT_FAMILY
    for candidate in preferred:
        if candidate.startswith("Manrope") and "Extra" not in candidate:
            FONT_FAMILY = candidate
            return FONT_FAMILY
    if preferred:
        FONT_FAMILY = preferred[0]
    return FONT_FAMILY


def app_font(size: int = 14, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_FAMILY)
    font.setPixelSize(size)
    font.setWeight(weight)
    # Full hinting keeps glyphs sharp under Windows ClearType / fractional DPI.
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    font.setStyleStrategy(
        QFont.StyleStrategy.PreferQuality | QFont.StyleStrategy.PreferAntialias
    )
    return font


def circular_pixmap(src: QPixmap, size: int) -> QPixmap:
    """Crop/scale pixmap into a circle of the given diameter."""
    if src.isNull() or size <= 0:
        return QPixmap()
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    scaled = src.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
        Qt.TransformationMode.SmoothTransformation,
    )
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawPixmap(x, y, scaled)
    painter.end()
    return out


def scroll_bar_qss() -> str:
    """Soft mint pill scrollbars used across content panes and tables."""
    return """
    QScrollBar:horizontal {
        background: rgba(6, 72, 61, 0.10);
        height: 10px;
        margin: 4px 10px 3px 10px;
        border: none;
        border-radius: 5px;
    }
    QScrollBar:vertical {
        background: rgba(6, 72, 61, 0.10);
        width: 10px;
        margin: 10px 3px 10px 4px;
        border: none;
        border-radius: 5px;
    }
    QScrollBar::handle:horizontal {
        background: #7BB8A8;
        border-radius: 5px;
        min-width: 40px;
    }
    QScrollBar::handle:vertical {
        background: #7BB8A8;
        border-radius: 5px;
        min-height: 40px;
    }
    QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {
        background: #08745F;
    }
    QScrollBar::handle:horizontal:pressed, QScrollBar::handle:vertical:pressed {
        background: #06483D;
    }
    QScrollBar::add-line, QScrollBar::sub-line {
        width: 0px;
        height: 0px;
        border: none;
        background: none;
    }
    QScrollBar::add-page, QScrollBar::sub-page {
        background: none;
    }
    """


def qss_global(family: str) -> str:
    return f"""
    * {{
        font-family: "{family}";
    }}
    QLabel, QPushButton, QLineEdit, QListWidget, QToolTip {{
        font-family: "{family}";
    }}
    QToolTip {{
        background: #0a4a38;
        color: #f5f7f6;
        border: 1px solid rgba(255,255,255,0.2);
        padding: 6px 10px;
        border-radius: 8px;
    }}
    {scroll_bar_qss()}
    """
