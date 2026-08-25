from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import MAIN_TEXT, app_font, scroll_bar_qss


class AgentOfferDialog(QDialog):
    ACCEPTED = 1
    DECLINED = 2

    def __init__(self, agent: dict, *, mine: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.decision = 0
        self.setWindowTitle(str(agent.get("title") or "Агент"))
        self.setModal(True)
        self.resize(440, 520)

        title = QLabel(str(agent.get("title") or "ИИ-агент"))
        title.setFont(app_font(18, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setWordWrap(True)

        hint = QLabel("Карточка агента из чата. Можно добавить к себе или отказаться.")
        if mine:
            hint.setText("Так выглядит отправленная карточка агента.")
        hint.setFont(app_font(12))
        hint.setStyleSheet("color: #6B7773; background: transparent;")
        hint.setWordWrap(True)

        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.10);"
            " border-radius: 16px; }"
        )
        fields = QVBoxLayout(card)
        fields.setContentsMargins(16, 14, 16, 14)
        fields.setSpacing(10)
        tools = agent.get("tools") if isinstance(agent.get("tools"), list) else []
        rows = (
            ("Описание", str(agent.get("description") or "не указано")),
            ("Цель", str(agent.get("goal") or "не указана")),
            ("Триггер", str(agent.get("trigger_summary") or agent.get("trigger_kind") or "не указан")),
            ("Инструменты", ", ".join(str(item) for item in tools) or "не указаны"),
        )
        for label, value in rows:
            caption = QLabel(label)
            caption.setFont(app_font(11, QFont.Weight.DemiBold))
            caption.setStyleSheet("color: #6B7773; background: transparent; border: none;")
            body = QLabel(value)
            body.setFont(app_font(13))
            body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")
            body.setWordWrap(True)
            fields.addWidget(caption)
            fields.addWidget(body)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card)
        scroll.setStyleSheet("QScrollArea { border: none; }" + scroll_bar_qss())

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        if mine:
            close_btn = QPushButton("Закрыть")
            close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            close_btn.setFixedHeight(40)
            close_btn.setStyleSheet(
                "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
                " border-radius: 12px; }"
            )
            close_btn.clicked.connect(self.reject)
            buttons.addWidget(close_btn)
        else:
            decline = QPushButton("Отказаться")
            decline.setCursor(Qt.CursorShape.PointingHandCursor)
            decline.setFixedHeight(40)
            decline.setStyleSheet(
                "QPushButton { background: #FFFFFF; color: #101817;"
                " border: 1px solid rgba(16,24,23,0.14); border-radius: 12px; }"
                "QPushButton:hover { background: #F3F7F5; }"
            )
            decline.clicked.connect(self._decline)
            accept = QPushButton("Добавить")
            accept.setCursor(Qt.CursorShape.PointingHandCursor)
            accept.setFixedHeight(40)
            accept.setStyleSheet(
                "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
                " border-radius: 12px; }"
                "QPushButton:hover { background: #0A8670; }"
            )
            accept.clicked.connect(self._accept)
            buttons.addWidget(decline, 1)
            buttons.addWidget(accept, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(scroll, 1)
        root.addLayout(buttons)

    def _accept(self) -> None:
        self.decision = self.ACCEPTED
        self.accept()

    def _decline(self) -> None:
        self.decision = self.DECLINED
        self.reject()
