from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.api_client import AgentDraft
from app.ui.theme import app_font


class MyAgentsPage(QWidget):
    continue_requested = Signal(str)
    delete_requested = Signal(str)

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
            empty = QLabel("Пока нет готовых ИИ-агентов. Сначала загрузите регламент и подтвердите функции.")
            empty.setWordWrap(True)
            empty.setFont(app_font(18))
            empty.setStyleSheet("color: #6B7773; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        self._list.addWidget(self._table_header())
        for draft in self._drafts:
            self._list.addWidget(self._row(draft))
        self._list.addStretch(1)

    def _table_header(self) -> QWidget:
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        layout = QGridLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setHorizontalSpacing(18)
        title = QLabel("Название агента")
        description = QLabel("Описание")
        action = QLabel("")
        for label in (title, description):
            label.setFont(app_font(12, QFont.Weight.DemiBold))
            label.setStyleSheet("color: #6B7773; background: transparent;")
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(action, 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return header

    def _row(self, draft: AgentDraft) -> QWidget:
        card = QFrame()
        card.setObjectName("AgentDraftRow")
        card.setStyleSheet(
            """
            QFrame#AgentDraftRow {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 16px;
            }
            """
        )
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(18)
        title = QLabel(_agent_title(draft))
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")
        title.setWordWrap(True)
        updated = _format_dt(draft.updated_at)
        description = QLabel(
            f"{draft.position or 'Должность не указана'} · {draft.department or 'Подразделение не указано'}"
            f"\nГотовность: {draft.progress}% · статус: {_status_label(draft.status)}"
            + (f" · изменён {updated}" if updated else "")
        )
        description.setFont(app_font(12))
        description.setStyleSheet("color: #6B7773; background: transparent;")
        description.setWordWrap(True)
        button = QPushButton("Создать")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, draft_id=draft.draft_id: self.continue_requested.emit(draft_id))
        delete = QPushButton("×")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setFixedWidth(36)
        delete.setToolTip("Удалить")
        delete.clicked.connect(lambda _checked=False, draft_id=draft.draft_id: self.delete_requested.emit(draft_id))
        actions = QHBoxLayout()
        actions.addWidget(button)
        actions.addWidget(delete)
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addLayout(actions, 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return card


def _agent_title(draft: AgentDraft) -> str:
    if draft.position:
        return f"ИИ-агент: {draft.position}"
    return draft.title or "ИИ-агент"


def _status_label(status: str) -> str:
    return {
        "draft": "черновик",
        "interview": "требует уточнений",
        "changes_pending": "готовится регламент",
        "ready": "готов к созданию",
        "finalized": "регламент дополнен",
    }.get(status, status or "черновик")


def _format_dt(value) -> str:
    if value is None:
        return ""
    return value.strftime("%d.%m.%Y %H:%M")
