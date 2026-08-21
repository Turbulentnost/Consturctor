"""Shared QSS for buttons, cards, inputs and chips. Palette stays emerald glass."""

from __future__ import annotations


def primary_button_qss(*, radius: int = 12, compact: bool = False) -> str:
    pad = "0 16px" if compact else "0 22px"
    height = "34px" if compact else "42px"
    return f"""
    QPushButton {{
        background: #08745F;
        color: #FFFFFF;
        border: 1px solid #076655;
        border-radius: {radius}px;
        padding: {pad};
        min-height: {height};
    }}
    QPushButton:hover {{
        background: #0C8A71;
        border-color: #0C8A71;
    }}
    QPushButton:pressed {{
        background: #06483D;
        border-color: #05382F;
    }}
    QPushButton:disabled {{
        background: #C5D5D0;
        color: #F7FBFA;
        border-color: #C5D5D0;
    }}
    """


def secondary_button_qss(*, radius: int = 12) -> str:
    return f"""
    QPushButton {{
        background: #FFFFFF;
        color: #06483D;
        border: 1px solid #D5DEDA;
        border-radius: {radius}px;
        padding: 0 16px;
        min-height: 42px;
    }}
    QPushButton:hover {{
        background: #EAF7F3;
        border-color: #08745F;
        color: #06483D;
    }}
    QPushButton:pressed {{
        background: #DFF3EC;
        border-color: #06483D;
    }}
    QPushButton:disabled {{
        background: #F7F9F8;
        color: #9DB3AD;
        border-color: #E4EBE8;
    }}
    """


def danger_button_qss(*, radius: int = 12) -> str:
    return f"""
    QPushButton {{
        background: #FFFFFF;
        color: #9B1C1C;
        border: 1px solid rgba(155,28,28,0.28);
        border-radius: {radius}px;
        padding: 0 16px;
        min-height: 42px;
    }}
    QPushButton:hover {{
        background: #FFF4F4;
        border-color: #B42318;
    }}
    QPushButton:pressed {{ background: #FEE4E2; }}
    QPushButton:disabled {{
        background: #F7F9F8;
        color: #9DB3AD;
        border-color: #E4EBE8;
    }}
    """


def ghost_button_qss() -> str:
    return """
    QPushButton {
        color: #06483D;
        background: transparent;
        border: none;
        border-radius: 10px;
        padding: 6px 10px;
        text-align: left;
    }
    QPushButton:hover {
        color: #08745F;
        background: rgba(8,116,95,0.08);
    }
    QPushButton:pressed { background: rgba(8,116,95,0.14); }
    """


def dark_primary_button_qss(*, radius: int = 16) -> str:
    return f"""
    QPushButton {{
        background: #06483D;
        color: #F7FBFA;
        border: 1px solid #05382F;
        border-radius: {radius}px;
        padding: 0 22px;
        min-height: 46px;
    }}
    QPushButton:hover {{
        background: #08745F;
        border-color: #08745F;
    }}
    QPushButton:pressed {{ background: #04342C; }}
    QPushButton:disabled {{
        background: #A8C8BF;
        color: #EAF7F3;
        border-color: #A8C8BF;
    }}
    """


def input_qss(*, radius: int = 14) -> str:
    return f"""
    QLineEdit, QPlainTextEdit {{
        background: #FFFFFF;
        color: #101817;
        border: 1px solid #D5DEDA;
        border-radius: {radius}px;
        padding: 10px 14px;
        selection-background-color: #08745F;
    }}
    QLineEdit:hover, QPlainTextEdit:hover {{
        border: 1px solid #B7C9C3;
    }}
    QLineEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid #08745F;
    }}
    """


def card_qss(
    object_name: str,
    *,
    radius: int = 18,
    hover: bool = False,
    selected: bool = False,
) -> str:
    hover_block = ""
    if hover:
        hover_block = f"""
        QFrame#{object_name}:hover {{
            border-color: rgba(8,116,95,0.40);
            background: #FBFDFC;
        }}
        """
    selected_block = ""
    if selected:
        selected_block = f"""
        QFrame#{object_name}[selected="true"] {{
            border: 1px solid #08745F;
            background: #F3FAF7;
        }}
        """
    return f"""
    QFrame#{object_name} {{
        background: #FFFFFF;
        border: 1px solid #E3EBE8;
        border-radius: {radius}px;
    }}
    {hover_block}
    {selected_block}
    """


def chip_qss(variant: str = "neutral", *, compact: bool = False) -> str:
    colors = {
        "neutral": ("#53625E", "#F4F7F6"),
        "mint": ("#0A5C48", "#DFF5EC"),
        "success": ("#08745F", "#EAF7F3"),
        "warning": ("#8A5300", "#FFF8E6"),
        "danger": ("#9B1C1C", "#FFF4F4"),
        "busy": ("#08745F", "#EAF7F3"),
    }
    fg, bg = colors.get(variant, colors["neutral"])
    pad = "1px 8px" if compact else "5px 12px"
    radius = "999px"
    return f"""
    QLabel {{
        color: {fg};
        background: {bg};
        border-radius: {radius};
        padding: {pad};
    }}
    """


def icon_button_qss(*, danger: bool = False) -> str:
    color = "#9B1C1C" if danger else "#06483D"
    hover_bg = "#FFF4F4" if danger else "#EAF7F3"
    hover_fg = "#B42318" if danger else "#08745F"
    from app.ui.theme import NERD_FAMILY

    return f"""
    QToolButton {{
        background: transparent;
        color: {color};
        border: none;
        border-radius: 10px;
        padding: 0;
        font-family: "{NERD_FAMILY}";
        font-size: 16px;
    }}
    QToolButton:hover {{
        background: {hover_bg};
        color: {hover_fg};
    }}
    QToolButton:pressed {{ background: #DFF3EC; }}
    QToolButton:disabled {{ color: #C5D0CC; background: transparent; }}
    """


def radio_qss() -> str:
    return """
    QRadioButton {
        color: #101817;
        background: transparent;
        spacing: 10px;
        padding: 6px 2px;
    }
    QRadioButton::indicator {
        width: 18px;
        height: 18px;
        border-radius: 9px;
        border: 1px solid rgba(16,24,23,0.22);
        background: #FFFFFF;
    }
    QRadioButton::indicator:hover {
        border: 1px solid #08745F;
    }
    QRadioButton::indicator:checked {
        border: 5px solid #08745F;
        background: #FFFFFF;
    }
    """


def tab_link_qss(*, active: bool) -> str:
    color = "#08745F" if active else "#6B7773"
    border = "#08745F" if active else "transparent"
    return f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-bottom: 2px solid {border};
        color: {color};
        padding: 6px 2px 8px 2px;
        text-align: left;
    }}
    QPushButton:hover {{
        color: #06483D;
        border-bottom-color: #08745F;
    }}
    """


def dialog_qss() -> str:
    return """
    QDialog#AppDialog {
        background: #FAFCFB;
    }
    QDialog#AppDialog QFrame#AppDialogCard {
        background: #FFFFFF;
        border: 1px solid #E3EBE8;
        border-radius: 20px;
    }
    """
