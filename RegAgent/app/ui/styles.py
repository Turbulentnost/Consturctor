"""Shared QSS for buttons, cards, inputs and chips. Palette stays emerald glass."""

from __future__ import annotations


def primary_button_qss(*, radius: int = 10, compact: bool = False) -> str:
    pad = "0 14px" if compact else "0 18px"
    return f"""
    QPushButton {{
        background: #08745F;
        color: #FFFFFF;
        border: none;
        border-radius: {radius}px;
        padding: {pad};
    }}
    QPushButton:hover {{ background: #0A8670; }}
    QPushButton:pressed {{ background: #06483D; }}
    QPushButton:disabled {{ background: #A8C8BF; color: #EAF7F3; }}
    """


def secondary_button_qss(*, radius: int = 10) -> str:
    return f"""
    QPushButton {{
        background: #FFFFFF;
        color: #06483D;
        border: 1px solid rgba(16,24,23,0.12);
        border-radius: {radius}px;
        padding: 0 14px;
    }}
    QPushButton:hover {{ background: #F4F7F6; }}
    QPushButton:pressed {{ background: #EAF1EE; }}
    QPushButton:disabled {{ background: #F4F7F6; color: #9DB3AD; }}
    """


def danger_button_qss(*, radius: int = 10) -> str:
    return f"""
    QPushButton {{
        background: #FFFFFF;
        color: #9B1C1C;
        border: 1px solid rgba(155,28,28,0.35);
        border-radius: {radius}px;
        padding: 0 14px;
    }}
    QPushButton:hover {{ background: #FFF4F4; border-color: #B42318; }}
    QPushButton:pressed {{ background: #FEE4E2; }}
    QPushButton:disabled {{
        background: #F4F7F6;
        color: #9DB3AD;
        border-color: rgba(16,24,23,0.10);
    }}
    """


def ghost_button_qss() -> str:
    return """
    QPushButton {
        color: #06483D;
        background: transparent;
        border: none;
        padding: 0 4px 0 0;
        text-align: left;
    }
    QPushButton:hover { color: #08745F; }
    """


def dark_primary_button_qss(*, radius: int = 23) -> str:
    return f"""
    QPushButton {{
        background: #06483D;
        color: #F7FBFA;
        border: none;
        border-radius: {radius}px;
        padding: 0 22px;
    }}
    QPushButton:hover {{ background: #08745F; }}
    QPushButton:pressed {{ background: #04342C; }}
    QPushButton:disabled {{ background: #A8C8BF; color: #EAF7F3; }}
    """


def input_qss(*, radius: int = 12) -> str:
    return f"""
    QLineEdit, QPlainTextEdit {{
        background: #FFFFFF;
        color: #101817;
        border: 1px solid rgba(16,24,23,0.10);
        border-radius: {radius}px;
        padding: 8px 12px;
        selection-background-color: #08745F;
    }}
    QLineEdit:hover, QPlainTextEdit:hover,
    QLineEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid #08745F;
    }}
    """


def card_qss(
    object_name: str,
    *,
    radius: int = 16,
    hover: bool = False,
    selected: bool = False,
) -> str:
    hover_block = ""
    if hover:
        hover_block = f"""
        QFrame#{object_name}:hover {{
            border-color: rgba(8,116,95,0.45);
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
        border: 1px solid rgba(16,24,23,0.10);
        border-radius: {radius}px;
    }}
    {hover_block}
    {selected_block}
    """


def chip_qss(variant: str = "neutral") -> str:
    colors = {
        "neutral": ("#53625E", "#F4F7F6"),
        "mint": ("#0A5C48", "#DFF5EC"),
        "success": ("#08745F", "#EAF7F3"),
        "warning": ("#8A5300", "#FFF8E6"),
        "danger": ("#9B1C1C", "#FFF4F4"),
        "busy": ("#08745F", "#EAF7F3"),
    }
    fg, bg = colors.get(variant, colors["neutral"])
    return f"""
    QLabel {{
        color: {fg};
        background: {bg};
        border-radius: 8px;
        padding: 4px 10px;
    }}
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
        padding: 4px 0 6px 0;
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
        border: 1px solid rgba(16,24,23,0.10);
        border-radius: 18px;
    }
    """
