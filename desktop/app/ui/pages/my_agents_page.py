from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.api_client import AgentDraft
from app.ui.theme import app_font


class MyAgentsPage(QWidget):
    continue_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drafts: list[AgentDraft] = []
        title = QLabel("Мои агенты")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        self._list = QVBoxLayout()
        self._list.setSpacing(12)
        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        list_widget.setLayout(self._list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(list_widget)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(scroll, 1)

    def set_drafts(self, drafts: list[AgentDraft]) -> None:
        self._drafts = drafts
        self._render()

    def _render(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._drafts:
            empty = QLabel("Пока нет черновиков. Создайте первого во вкладке «Создать».")
            empty.setWordWrap(True)
            empty.setFont(app_font(18))
            empty.setStyleSheet("color: #6B7773; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        for draft in self._drafts:
            self._list.addWidget(self._card(draft))
        self._list.addStretch(1)

    def _card(self, draft: AgentDraft) -> QWidget:
        card = QFrame()
        card.setObjectName("AgentDraftCard")
        card.setStyleSheet(
            """
            QFrame#AgentDraftCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 16px;
            }
            """
        )
        layout = QHBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        text = QVBoxLayout()
        title = QLabel(draft.title or "Черновик ИИ-агента")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")
        title.setWordWrap(True)
        meta = QLabel(f"{draft.position} · {draft.department} · готовность {draft.progress}% · {draft.status}")
        meta.setFont(app_font(12))
        meta.setStyleSheet("color: #6B7773; background: transparent;")
        meta.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(meta)
        layout.addLayout(text, 1)
        button = QPushButton("Продолжить")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, draft_id=draft.draft_id: self.continue_requested.emit(draft_id))
        layout.addWidget(button)
        return card
