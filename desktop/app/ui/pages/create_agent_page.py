from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.theme import app_font


class CreateAgentPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel("Создать агента")
        title.setFont(app_font(26, QFont.Weight.Bold))
        title.setStyleSheet("color: #121a17; background: transparent;")

        body = QLabel(
            "Здесь появится конструктор ИИ-агента: описание задачи, "
            "документы, настройки и сценарий работы."
        )
        body.setWordWrap(True)
        body.setFont(app_font(14))
        body.setStyleSheet("color: #5a6b63; background: transparent;")
        body.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)
