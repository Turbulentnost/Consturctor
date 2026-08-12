from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

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
COLOR_ACTIVE_BG = WHITE
COLOR_ACTIVE_FG = MAIN_TEXT
COLOR_CONTENT_BG = QColor("#FAFCFB")
COLOR_CONTENT_MUTED = QColor("#6B7773")

SIDEBAR_EXPANDED = 216
SIDEBAR_COLLAPSED = 78
NAV_ITEM_HEIGHT = 44
NAV_ITEM_RADIUS = 16
SIDEBAR_PADDING_X = 16
CONTENT_PADDING_X = 36
CONTENT_PADDING_TOP = 30

FONT_FAMILY = "Segoe UI"


def load_fonts() -> str:
    """Prefer Manrope if installed; otherwise Segoe UI / system UI."""
    global FONT_FAMILY
    for family in QFontDatabase.families():
        if family == "Manrope":
            FONT_FAMILY = family
            return FONT_FAMILY
    for family in QFontDatabase.families():
        if family.startswith("Manrope"):
            FONT_FAMILY = family
            return FONT_FAMILY
    FONT_FAMILY = "Segoe UI"
    return FONT_FAMILY


def app_font(size: int = 14, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(FONT_FAMILY, size)
    font.setWeight(weight)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    return font


def qss_global(family: str) -> str:
    return f"""
    * {{
        font-family: "{family}";
    }}
    QToolTip {{
        background: #0a4a38;
        color: #f5f7f6;
        border: 1px solid rgba(255,255,255,0.2);
        padding: 6px 10px;
        border-radius: 8px;
    }}
    """
