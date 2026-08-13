from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.api_client import AgentDraft, AgentSuggestion
from app.ui.theme import app_font


_TITLE_COL_WIDTH = 320
_DESC_COL_WIDTH = 460


class MyAgentsPage(QWidget):
    continue_requested = Signal(str)
    create_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drafts: list[AgentDraft] = []
        self._suggestions: list[AgentSuggestion] | None = None
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
        latest_with_suggestions = next((draft for draft in drafts if draft.agent_suggestions), None)
        self._suggestions = latest_with_suggestions.agent_suggestions if latest_with_suggestions else None
        self._render()

    def set_agent_suggestions(self, suggestions: list[AgentSuggestion]) -> None:
        self._suggestions = suggestions
        self._render()

    def find_suggestion(self, agent_id: str) -> AgentSuggestion | None:
        for item in self._suggestions or []:
            if item.agent_id == agent_id:
                return item
        for draft in self._drafts:
            for item in draft.agent_suggestions or []:
                if item.agent_id == agent_id:
                    return item
        return None

    def _render(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._suggestions is not None:
            self._render_suggestions()
            return
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

    def _render_suggestions(self) -> None:
        suggestions = self._suggestions or []
        if not suggestions:
            empty = QLabel("Для этого сотрудника не найдено бизнес-процессов для ИИ-агентов.")
            empty.setWordWrap(True)
            empty.setFont(app_font(18))
            empty.setStyleSheet("color: #6B7773; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        self._list.addWidget(self._table_header())
        for suggestion in suggestions:
            self._list.addWidget(self._suggestion_row(suggestion))
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
        title.setFixedWidth(_TITLE_COL_WIDTH)
        description.setFixedWidth(_DESC_COL_WIDTH)
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
        title.setFixedWidth(_TITLE_COL_WIDTH)
        updated = _format_dt(draft.updated_at)
        description = QLabel(
            f"{draft.position or 'Должность не указана'} · {draft.department or 'Подразделение не указано'}"
            f"\nГотовность: {draft.progress}% · статус: {_status_label(draft.status)}"
            + (f" · изменён {updated}" if updated else "")
        )
        description.setFont(app_font(12))
        description.setStyleSheet("color: #6B7773; background: transparent;")
        description.setWordWrap(True)
        description.setFixedWidth(_DESC_COL_WIDTH)
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

    def _suggestion_row(self, suggestion: AgentSuggestion) -> QWidget:
        card = QFrame()
        card.setObjectName("AgentSuggestionRow")
        card.setStyleSheet(
            """
            QFrame#AgentSuggestionRow {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 16px;
            }
            """
        )
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(18)
        title = QLabel(suggestion.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")
        title.setWordWrap(True)
        title.setFixedWidth(_TITLE_COL_WIDTH)
        description = QLabel(suggestion.description or "Бизнес-процесс найден в сформированном регламенте.")
        description.setFont(app_font(12))
        description.setStyleSheet("color: #6B7773; background: transparent;")
        description.setWordWrap(True)
        description.setFixedWidth(_DESC_COL_WIDTH)
        create = QPushButton("Создать")
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.clicked.connect(
            lambda _checked=False, agent_id=suggestion.agent_id: self.create_requested.emit(agent_id)
        )
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(create, 0, 2)
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
