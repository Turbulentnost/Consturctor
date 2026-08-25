from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QByteArray, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.chat.models import ChatMessage
from app.chat.widgets.agent_share_card import AgentShareCard
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

_TICK_COLOR = "#FFFFFF"
_BUBBLE_MINE = "#08745F"
_FAIL_COLOR = "#FFB4B0"

_SVG_SINGLE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 14" fill="none">
  <path d="M1.55 7.2 6.05 11.45 14.65 2.5" stroke="{color}" stroke-width="1.85"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_SVG_DOUBLE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 22 14" fill="none">
  <path d="M1.4 7.2 5.9 11.45 9.35 7.75" stroke="{color}" stroke-width="1.85"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M7.45 7.2 11.95 11.45 20.55 2.5" stroke="{bg}" stroke-width="3.4"
        stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M7.45 7.2 11.95 11.45 20.55 2.5" stroke="{color}" stroke-width="1.85"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_SVG_CLOCK = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14" fill="none">
  <circle cx="7" cy="7" r="5.15" stroke="{color}" stroke-width="1.45"/>
  <path d="M7 4.35 V7.15 L9.05 8.55" stroke="{color}" stroke-width="1.45"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""


def _clock(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%H:%M")
    except ValueError:
        return value[11:16] if len(value) >= 16 else value


def _dpr() -> float:
    app = QApplication.instance()
    if app is None:
        return 1.0
    screen = app.primaryScreen()
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def _svg_pixmap(svg: str, width: int, height: int) -> QPixmap:
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


class ReceiptMark(QLabel):
    def __init__(self, status: str, *, on_light: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_light = on_light
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background: transparent;")
        self.set_status(status)

    def set_status(self, status: str) -> None:
        tick = "#08745F" if self._on_light else _TICK_COLOR
        mask = "#FFFFFF" if self._on_light else _BUBBLE_MINE
        if status == "failed":
            self.clear()
            self.setText("!")
            self.setFixedSize(12, 14)
            self.setStyleSheet(f"color: {_FAIL_COLOR}; background: transparent;")
            return
        self.setText("")
        self.setStyleSheet("background: transparent;")
        if status == "sending":
            svg, w, h = _SVG_CLOCK.format(color=tick), 14, 14
        elif status == "read":
            svg, w, h = _SVG_DOUBLE.format(color=tick, bg=mask), 20, 14
        else:
            svg, w, h = _SVG_SINGLE.format(color=tick), 16, 14
        self.setPixmap(_svg_pixmap(svg, w, h))
        self.setFixedSize(w, h)


class MessageBubble(QWidget):
    agent_opened = Signal(object, bool)

    def __init__(self, message: ChatMessage, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.message = message
        mine = message.mine
        root = QHBoxLayout(self)
        root.setContentsMargins(8, 2, 8, 2)
        card_only = bool(message.agent) and not message.text and not message.attachments
        card = QFrame()
        card.setObjectName("msgCloud")
        card.setMaximumWidth(520)
        card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        if card_only:
            card.setStyleSheet("QFrame#msgCloud { background: transparent; border: none; }")
        elif mine:
            card.setStyleSheet(
                "QFrame#msgCloud { background: #08745F; border: none; border-radius: 14px; }"
            )
        else:
            card.setStyleSheet(
                "QFrame#msgCloud { background: #FFFFFF; border: 1px solid rgba(8, 116, 95, 0.22);"
                " border-radius: 14px; }"
            )
        inner = QVBoxLayout(card)
        inner.setContentsMargins(0 if card_only else 12, 8, 0 if card_only else 12, 8)
        inner.setSpacing(6)
        body = QLabel(message.text or "")
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        body.setFont(app_font(13))
        body.setStyleSheet(
            f"color: {'#FFFFFF' if mine else MAIN_TEXT.name()}; background: transparent;"
        )
        if message.text:
            inner.addWidget(body)
        if message.agent:
            card_agent = AgentShareCard(message.agent)
            card_agent.clicked.connect(lambda payload: self.agent_opened.emit(payload, mine))
            inner.addWidget(card_agent)
        for item in message.attachments:
            attach = QLabel(f"📎 {item.filename}")
            attach.setStyleSheet(
                f"color: {'#EAF7F3' if mine else '#06483D'}; background: transparent;"
            )
            attach.setFont(app_font(12))
            inner.addWidget(attach)
        meta = QHBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(4)
        time_lbl = QLabel(_clock(message.created_at))
        time_lbl.setFont(app_font(11))
        time_color = COLOR_CONTENT_MUTED.name() if card_only or not mine else "#D5EDE6"
        time_lbl.setStyleSheet(
            f"color: {time_color}; background: transparent;"
        )
        meta.addWidget(time_lbl)
        self._mark: ReceiptMark | None = None
        if mine:
            self._mark = ReceiptMark(message.receipt, on_light=card_only)
            meta.addWidget(self._mark, 0, Qt.AlignmentFlag.AlignVCenter)
        meta.addStretch(1)
        inner.addLayout(meta)
        if mine:
            root.addStretch(1)
            root.addWidget(card, 0, Qt.AlignmentFlag.AlignRight)
        else:
            root.addWidget(card, 0, Qt.AlignmentFlag.AlignLeft)
            root.addStretch(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_receipt(self, status: str) -> None:
        self.message.receipt = status
        if self._mark is None:
            return
        self._mark.set_status(status)
