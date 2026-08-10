from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.ui.theme import app_font


class MyAgentsPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        title = QLabel("Мои агенты")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        body = QLabel("Пока нет агентов. Создайте первого во вкладке «Создать агента».")
        body.setWordWrap(True)
        body.setFont(app_font(18))
        body.setStyleSheet("color: #6B7773; background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(body)
        layout.addStretch(1)
