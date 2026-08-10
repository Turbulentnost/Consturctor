from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor, QFont, QFontDatabase

WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800

# Emerald → black glass palette (reference)
COLOR_BG_TOP = QColor("#0a4a38")
COLOR_BG_MID = QColor("#062e24")
COLOR_BG_BOTTOM = QColor("#000000")
COLOR_GLASS = QColor(10, 74, 56, 160)
COLOR_GLASS_BORDER = QColor(255, 255, 255, 28)
COLOR_TEXT = QColor("#f5f7f6")
COLOR_TEXT_MUTED = QColor(255, 255, 255, 170)
COLOR_ACTIVE_BG = QColor("#ffffff")
COLOR_ACTIVE_FG = QColor("#0a1210")
COLOR_ACCENT_ERROR = QColor("#ff8a80")
COLOR_CONTENT_BG = QColor("#f7faf8")
COLOR_CONTENT_TEXT = QColor("#121a17")
COLOR_CONTENT_MUTED = QColor("#5a6b63")

SIDEBAR_EXPANDED = 228
SIDEBAR_COLLAPSED = 78
NAV_ITEM_HEIGHT = 48
NAV_ITEM_RADIUS = 24

FONT_FAMILY = "Manrope"

_ASSETS = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def load_fonts() -> str:
    """Load bundled Manrope fonts; return family name to use."""
    global FONT_FAMILY
    preferred: list[str] = []
    # Variable face first — clean family name "Manrope"
    for name in (
        "Manrope-Variable.ttf",
        "Manrope-Regular.ttf",
        "Manrope-SemiBold.ttf",
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
