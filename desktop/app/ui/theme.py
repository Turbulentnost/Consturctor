from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

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
        QFont.StyleStrategy.PreferQuality
        | QFont.StyleStrategy.PreferAntialias
        | QFont.StyleStrategy.NoFontMerging
    )
    return font


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
    """
