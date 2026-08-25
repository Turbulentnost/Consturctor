from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.api_client import BoardAgent
from app.ui.theme import MAIN_TEXT, app_font


class AgentPickerDialog(QDialog):
    def __init__(self, agents: list[BoardAgent], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chosen: BoardAgent | None = None
        self.setWindowTitle("Отправить агента")
        self.setModal(True)
        self.resize(420, 460)
        title = QLabel("Выберите агента")
        title.setFont(app_font(18, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        hint = QLabel("В чат уйдёт карточка: название и краткое описание.")
        hint.setFont(app_font(12))
        hint.setStyleSheet("color: #6B7773; background: transparent;")
        hint.setWordWrap(True)

        list_host = QWidget()
        column = QVBoxLayout(list_host)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(8)
        for agent in agents:
            column.addWidget(self._row(agent))
        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(list_host)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(scroll, 1)

    def _row(self, agent: BoardAgent) -> QFrame:
        card = QFrame()
        card.setObjectName("agentPickRow")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(
            """
            QFrame#agentPickRow {
                background: #FFFFFF;
                border: 1px solid rgba(8, 116, 95, 0.14);
                border-radius: 12px;
            }
            QFrame#agentPickRow:hover {
                background: #F3FAF7;
                border: 1px solid #08745F;
            }
            """
        )
        icon = QLabel((agent.title[:1] or "А").upper())
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(36, 36)
        icon.setFont(app_font(16, QFont.Weight.DemiBold))
        icon.setStyleSheet("background: #EAF7F3; color: #08745F; border-radius: 10px;")
        name = QLabel(agent.title or "ИИ-агент")
        name.setFont(app_font(13, QFont.Weight.DemiBold))
        name.setStyleSheet("color: #101817; background: transparent; border: none;")
        name.setWordWrap(True)
        desc = QLabel(agent.description or "Описание не указано")
        desc.setFont(app_font(11))
        desc.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        desc.setWordWrap(True)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(desc)
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        card.mousePressEvent = lambda event, item=agent: self._pick(item)  # type: ignore[method-assign]
        return card

    def _pick(self, agent: BoardAgent) -> None:
        self.chosen = agent
        self.accept()
