from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from app.chat.models import ChatThread
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


def _clock(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone().strftime("%H:%M")
    except ValueError:
        return value[11:16] if len(value) >= 16 else value


def _snippet(text: str, limit: int = 56) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


class ThreadCard(QFrame):
    def __init__(self, thread: ChatThread, *, selected: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("threadCard")
        self.setProperty("selected", selected)
        self.setFixedHeight(78)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            """
            QFrame#threadCard {
                background: #FFFFFF;
                border: 1px solid rgba(6, 72, 61, 0.10);
                border-radius: 14px;
            }
            QFrame#threadCard[selected="true"] {
                background: #E7F3EE;
                border: 1px solid rgba(8, 116, 95, 0.28);
            }
            """
        )

        title = QLabel(thread.title or "Диалог")
        title.setFont(app_font(14, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        time_lbl = QLabel(_clock(thread.last_message_at))
        time_lbl.setFont(app_font(11))
        time_lbl.setStyleSheet(
            f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; border: none;"
        )
        time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        top.addWidget(title, 1)
        top.addWidget(time_lbl, 0)

        preview = QLabel(_snippet(thread.preview) or "Нет сообщений")
        preview.setFont(app_font(12))
        preview.setStyleSheet(
            f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; border: none;"
        )
        preview.setWordWrap(True)
        preview.setMaximumHeight(34)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(4)
        root.addLayout(top)
        root.addWidget(preview)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(280, 78)
