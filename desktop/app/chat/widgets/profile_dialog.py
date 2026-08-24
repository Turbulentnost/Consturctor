from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.chat.models import ChatThread
from app.ui.theme import MAIN_TEXT, app_font


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


class ChatProfileDialog(QDialog):
    def __init__(self, thread: ChatThread, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Профиль")
        self.setModal(True)
        self.setFixedWidth(380)
        status = "В сети" if thread.online else {
            "busy": "Занят",
            "away": "Не активен",
        }.get(thread.activity_status, "Не в сети")
        if thread.id == "support":
            status = "В сети"

        avatar = QLabel(_initials(thread.title))
        avatar.setFixedSize(72, 72)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(app_font(22, QFont.Weight.DemiBold))
        avatar.setStyleSheet(
            "background: #08745F; color: #FFFFFF; border-radius: 36px;"
        )

        name = QLabel(thread.title or "Диалог")
        name.setFont(app_font(18, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        name.setWordWrap(True)
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.10);"
            " border-radius: 16px; }"
        )
        rows = QVBoxLayout(card)
        rows.setContentsMargins(16, 14, 16, 14)
        rows.setSpacing(10)
        for label, value in (
            ("Должность", thread.position or "не указана"),
            ("Отдел", thread.department or "не указан"),
            ("Статус", status),
        ):
            caption = QLabel(label)
            caption.setFont(app_font(11, QFont.Weight.DemiBold))
            caption.setStyleSheet("color: #6B7773; background: transparent; border: none;")
            body = QLabel(value)
            body.setFont(app_font(13))
            body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")
            body.setWordWrap(True)
            rows.addWidget(caption)
            rows.addWidget(body)

        close_btn = QPushButton("Закрыть")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedHeight(40)
        close_btn.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
            " border-radius: 12px; }"
            "QPushButton:hover { background: #0A8670; }"
        )
        close_btn.clicked.connect(self.accept)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        root.setSpacing(14)
        head = QHBoxLayout()
        head.addStretch(1)
        head.addWidget(avatar)
        head.addStretch(1)
        root.addLayout(head)
        root.addWidget(name)
        root.addWidget(card)
        root.addWidget(close_btn)
