from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from app.ui.theme import app_font


class AgentShareCard(QFrame):
    def __init__(self, agent: dict, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("agentShareCard")
        self.setStyleSheet(
            """
            QFrame#agentShareCard {
                background: #FFFFFF;
                border: 1px solid rgba(8, 116, 95, 0.18);
                border-radius: 12px;
            }
            """
        )
        self.setMinimumWidth(220)
        self.setMaximumWidth(360)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

        title = str(agent.get("title") or "ИИ-агент")
        description = str(agent.get("description") or agent.get("goal") or "Описание не указано")
        trigger = str(agent.get("trigger_summary") or "")

        icon = QLabel((title[:1] or "А").upper())
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(36, 36)
        icon.setFont(app_font(16, QFont.Weight.DemiBold))
        icon.setStyleSheet(
            "background: #EAF7F3; color: #08745F; border-radius: 10px; font-weight: 700;"
        )

        kind = QLabel("Агент")
        kind.setFont(app_font(10, QFont.Weight.DemiBold))
        kind.setStyleSheet("color: #08745F; background: transparent; border: none;")

        name = QLabel(title)
        name.setFont(app_font(13, QFont.Weight.DemiBold))
        name.setStyleSheet("color: #101817; background: transparent; border: none;")
        name.setWordWrap(True)

        desc = QLabel(description)
        desc.setFont(app_font(11))
        desc.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        desc.setWordWrap(True)
        desc.setMaximumHeight(40)

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(kind)
        text.addWidget(name)
        text.addWidget(desc)
        if trigger:
            meta = QLabel(trigger)
            meta.setFont(app_font(10))
            meta.setStyleSheet("color: #6B7773; background: transparent; border: none;")
            meta.setWordWrap(True)
            text.addWidget(meta)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
