from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentDraft, AgentRunHistoryItem, AgentSuggestion, WorkflowListItem
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


_TITLE_COL_WIDTH = 300
_DESC_COL_WIDTH = 360
_ACTION_COL_WIDTH = 160
_PRIMARY_ACTION_QSS = """
QPushButton {
    background: #08745F;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 0 14px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:pressed { background: #06483D; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_DANGER_ACTION_QSS = """
QPushButton {
    background: #FFFFFF;
    color: #9B1C1C;
    border: 1px solid rgba(155,28,28,0.35);
    border-radius: 10px;
    padding: 0 14px;
}
QPushButton:hover { background: #FFF4F4; border-color: #B42318; }
QPushButton:pressed { background: #FEE4E2; }
QPushButton:disabled { background: #F4F7F6; color: #9DB3AD; border-color: rgba(16,24,23,0.10); }
"""
_SECONDARY_ACTION_QSS = """
QPushButton {
    background: #FFFFFF;
    color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 10px;
    padding: 0 14px;
}
QPushButton:hover { background: #F4F7F6; }
QPushButton:pressed { background: #EAF1EE; }
"""


class MyAgentsPage(QWidget):
    continue_requested = Signal(str)
    create_requested = Signal(str)
    create_suggestion_requested = Signal(str, str)
    delete_requested = Signal(str)
    delete_suggestion_requested = Signal(str, str)
    delete_agent_requested = Signal(str)
    run_agent_requested = Signal(str)
    history_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drafts: list[AgentDraft] = []
        self._agents: list[WorkflowListItem] = []
        self._suggestions: list[AgentSuggestion] = []
        self._suggestion_draft_ids: dict[str, str] = {}
        self._active_view = "agents"
        title = QLabel("Мои агенты")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        self._agents_link = self._nav_link("Мои агенты")
        self._drafts_link = self._nav_link("Черновики")
        self._agents_link.clicked.connect(lambda: self._set_view("agents"))
        self._drafts_link.clicked.connect(lambda: self._set_view("drafts"))
        links = QHBoxLayout()
        links.setContentsMargins(8, 0, 0, 0)
        links.setSpacing(18)
        links.addWidget(self._agents_link)
        links.addWidget(self._drafts_link)
        links.addStretch(1)

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
        layout.addLayout(links)
        layout.addWidget(scroll, 1)
        self._update_nav_links()

    def show_agents(self) -> None:
        self._set_view("agents")

    def show_drafts(self) -> None:
        self._set_view("drafts")

    def set_agents(self, agents: list[WorkflowListItem]) -> None:
        self._agents = [agent for agent in agents if agent.phase == "done"]
        self._render()

    def set_drafts(self, drafts: list[AgentDraft]) -> None:
        self._drafts = drafts
        self._suggestions, self._suggestion_draft_ids = _collect_agent_suggestions(drafts)
        self._render()

    def set_agent_suggestions(self, suggestions: list[AgentSuggestion]) -> None:
        self._suggestions = suggestions
        self._suggestion_draft_ids = {}
        self._set_view("drafts", render=False)
        self._render()

    def find_suggestion(self, agent_id: str, *, draft_id: str = "") -> AgentSuggestion | None:
        if draft_id:
            for draft in self._drafts:
                if draft.draft_id != draft_id:
                    continue
                for item in draft.agent_suggestions or []:
                    if item.agent_id == agent_id:
                        return item
        for item in self._suggestions:
            if item.agent_id == agent_id:
                return item
        for draft in self._drafts:
            for item in draft.agent_suggestions or []:
                if item.agent_id == agent_id:
                    return item
        return None

    def _nav_link(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFont(app_font(14, QFont.Weight.DemiBold))
        button.setStyleSheet(_tab_link_qss(active=False))
        return button

    def _set_view(self, view: str, *, render: bool = True) -> None:
        if view not in {"agents", "drafts"}:
            return
        self._active_view = view
        self._update_nav_links()
        if render:
            self._render()

    def _update_nav_links(self) -> None:
        self._agents_link.setStyleSheet(_tab_link_qss(active=self._active_view == "agents"))
        self._drafts_link.setStyleSheet(_tab_link_qss(active=self._active_view == "drafts"))

    def _render(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._active_view == "agents":
            self._render_agents()
            return
        self._render_drafts()

    def _render_drafts(self) -> None:
        has_items = bool(self._drafts or self._suggestions)
        if not has_items:
            empty = QLabel("Пока нет черновиков. Незавершённые агенты появятся здесь.")
            empty.setWordWrap(True)
            empty.setFont(app_font(18))
            empty.setStyleSheet("color: #6B7773; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        self._list.addWidget(self._table_header())
        rendered_suggestions: set[tuple[str, str]] = set()
        for draft in self._drafts:
            if draft.agent_suggestions:
                for suggestion in draft.agent_suggestions:
                    rendered_suggestions.add((draft.draft_id, suggestion.agent_id))
                    self._list.addWidget(
                        self._suggestion_row(
                            suggestion,
                            draft_id=draft.draft_id,
                            created_at=draft.created_at,
                        )
                    )
            else:
                self._list.addWidget(self._row(draft))
        for suggestion in self._suggestions:
            draft_id = self._suggestion_draft_ids.get(suggestion.agent_id, "")
            if (draft_id, suggestion.agent_id) not in rendered_suggestions:
                created_at = next(
                    (item.created_at for item in self._drafts if item.draft_id == draft_id),
                    None,
                )
                self._list.addWidget(
                    self._suggestion_row(suggestion, draft_id=draft_id, created_at=created_at)
                )
        self._list.addStretch(1)

    def _render_agents(self) -> None:
        if not self._agents:
            empty = QLabel("Пока нет опубликованных ИИ-агентов. Созданные и опубликованные агенты появятся здесь.")
            empty.setWordWrap(True)
            empty.setFont(app_font(18))
            empty.setStyleSheet("color: #6B7773; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        self._list.addWidget(self._table_header())
        for agent in self._agents:
            self._list.addWidget(self._agent_row(agent))
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
        button.setStyleSheet(_PRIMARY_ACTION_QSS)
        button.clicked.connect(lambda _checked=False, draft_id=draft.draft_id: self.continue_requested.emit(draft_id))
        delete = QPushButton("Удалить")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setStyleSheet(_DANGER_ACTION_QSS)
        delete.setToolTip("Удалить")
        delete.clicked.connect(lambda _checked=False, draft_id=draft.draft_id: self.delete_requested.emit(draft_id))
        actions = _actions_widget(button, delete, created_at=draft.created_at)
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(actions, 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return card

    def _suggestion_row(
        self,
        suggestion: AgentSuggestion,
        *,
        draft_id: str = "",
        created_at: datetime | None = None,
    ) -> QWidget:
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
        create.setStyleSheet(_PRIMARY_ACTION_QSS)
        create.clicked.connect(
            lambda _checked=False, did=draft_id, agent_id=suggestion.agent_id: (
                self.create_suggestion_requested.emit(did, agent_id)
                if did
                else self.create_requested.emit(agent_id)
            )
        )
        delete = QPushButton("Удалить")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setStyleSheet(_DANGER_ACTION_QSS)
        delete.setEnabled(bool(draft_id))
        delete.setToolTip("Удалить черновик" if draft_id else "Черновик можно удалить после обновления списка")
        delete.clicked.connect(
            lambda _checked=False, did=draft_id, agent_id=suggestion.agent_id: self.delete_suggestion_requested.emit(
                did,
                agent_id,
            )
        )
        actions = _actions_widget(create, delete, created_at=created_at)
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(actions, 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return card

    def _agent_row(self, agent: WorkflowListItem) -> QWidget:
        card = QFrame()
        card.setObjectName("PublishedAgentRow")
        card.setStyleSheet(
            """
            QFrame#PublishedAgentRow {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 16px;
            }
            """
        )
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(18)
        title = QLabel(agent.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")
        title.setWordWrap(True)
        title.setFixedWidth(_TITLE_COL_WIDTH)
        description = QLabel(
            "Опубликован"
            + (f"\nДокумент: {agent.document_name}" if agent.document_name else "")
            + (f"\nОбновлён: {agent.updated_at[:19]}" if agent.updated_at else "")
        )
        description.setFont(app_font(12))
        description.setStyleSheet("color: #6B7773; background: transparent;")
        description.setWordWrap(True)
        description.setFixedWidth(_DESC_COL_WIDTH)
        run = QPushButton("Запустить")
        run.setCursor(Qt.CursorShape.PointingHandCursor)
        run.setStyleSheet(_PRIMARY_ACTION_QSS)
        run.clicked.connect(
            lambda _checked=False, workflow_id=agent.id: self.run_agent_requested.emit(workflow_id)
        )
        history = QPushButton("История")
        history.setCursor(Qt.CursorShape.PointingHandCursor)
        history.setStyleSheet(_SECONDARY_ACTION_QSS)
        history.clicked.connect(
            lambda _checked=False, workflow_id=agent.id, name=agent.title: self.history_requested.emit(
                workflow_id, name or "ИИ-агент"
            )
        )
        delete = QPushButton("Удалить")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setStyleSheet(_DANGER_ACTION_QSS)
        delete.clicked.connect(lambda _checked=False, workflow_id=agent.id: self.delete_agent_requested.emit(workflow_id))
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(_actions_widget(run, history, delete), 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return card


class AgentHistoryDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        runs: list[AgentRunHistoryItem],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("История запусков")
        self.setModal(True)
        self.resize(560, 520)
        self.setStyleSheet("QDialog { background: #F4F7F6; }")

        heading = QLabel(title or "ИИ-агент")
        heading.setFont(app_font(18, QFont.Weight.DemiBold))
        heading.setWordWrap(True)
        heading.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("История запусков")
        subtitle.setFont(app_font(12))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        card = QFrame()
        card.setObjectName("HistoryCard")
        card.setStyleSheet(
            """
            QFrame#HistoryCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 16px;
            }
            """
        )
        list_layout = QVBoxLayout(card)
        list_layout.setContentsMargins(16, 14, 16, 14)
        list_layout.setSpacing(10)
        if not runs:
            empty = QLabel("Запусков ещё не было")
            empty.setFont(app_font(13))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            list_layout.addWidget(empty)
        else:
            for item in runs:
                list_layout.addWidget(_history_row(item))
        list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        close_btn = QPushButton("Закрыть")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setFixedHeight(36)
        close_btn.setStyleSheet(_SECONDARY_ACTION_QSS)
        close_btn.clicked.connect(self.accept)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)
        root.addWidget(heading)
        root.addWidget(subtitle)
        root.addWidget(scroll, 1)
        root.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignRight)


def _history_row(item: AgentRunHistoryItem) -> QWidget:
    row = QFrame()
    row.setStyleSheet(
        "QFrame { background: #F7FAF9; border: 1px solid #EAF1EE; border-radius: 12px; }"
    )
    layout = QVBoxLayout(row)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(4)
    when = _format_iso(item.started_at) or "—"
    source = "триггер" if item.source == "trigger" else "чат"
    status = "готово" if item.status == "ok" else ("ошибка" if item.status == "error" else item.status or "в работе")
    meta = QLabel(f"{when}  ·  {source}  ·  {status}")
    meta.setFont(app_font(11, QFont.Weight.DemiBold))
    meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    task = QLabel(item.message.strip() or "Типовая задача агента")
    task.setFont(app_font(13, QFont.Weight.DemiBold))
    task.setWordWrap(True)
    task.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
    answer = (item.answer or "").strip()
    if len(answer) > 280:
        answer = answer[:280].rstrip() + "…"
    body = QLabel(answer or "Нет текста результата")
    body.setFont(app_font(12))
    body.setWordWrap(True)
    body.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    layout.addWidget(meta)
    layout.addWidget(task)
    layout.addWidget(body)
    return row


def _format_iso(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:19].replace("T", " ")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%d.%m.%Y %H:%M")


def _agent_title(draft: AgentDraft) -> str:
    if draft.position:
        return f"ИИ-агент: {draft.position}"
    return draft.title or "ИИ-агент"


def _actions_widget(*buttons: QPushButton, created_at: datetime | None = None) -> QWidget:
    widget = QWidget()
    widget.setStyleSheet("background: transparent;")
    widget.setFixedWidth(_ACTION_COL_WIDTH)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    for button in buttons:
        button.setFixedWidth(_ACTION_COL_WIDTH)
        button.setFixedHeight(34)
        button.setFont(app_font(12, QFont.Weight.DemiBold))
        layout.addWidget(button)
    date_text, time_text = _format_created_parts(created_at)
    if date_text:
        date_label = QLabel(date_text)
        date_label.setFont(app_font(11))
        date_label.setStyleSheet("color: #6B7773; background: transparent;")
        date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(date_label)
        time_label = QLabel(time_text)
        time_label.setFont(app_font(11))
        time_label.setStyleSheet("color: #6B7773; background: transparent;")
        time_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(time_label)
    layout.addStretch(1)
    return widget


def _collect_agent_suggestions(drafts: list[AgentDraft]) -> tuple[list[AgentSuggestion], dict[str, str]]:
    suggestions: list[AgentSuggestion] = []
    draft_ids: dict[str, str] = {}
    seen: set[tuple[str, str, str]] = set()
    for draft in drafts:
        for suggestion in draft.agent_suggestions or []:
            key = (suggestion.agent_id, suggestion.title, suggestion.description)
            if key in seen:
                continue
            seen.add(key)
            draft_ids[suggestion.agent_id] = draft.draft_id
            suggestions.append(suggestion)
    return suggestions, draft_ids


def _tab_link_qss(*, active: bool) -> str:
    color = "#08745F" if active else "#6B7773"
    border = "#08745F" if active else "transparent"
    return f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-bottom: 2px solid {border};
        color: {color};
        padding: 4px 0 6px 0;
        text-align: left;
    }}
    QPushButton:hover {{
        color: #06483D;
        border-bottom-color: #08745F;
    }}
    """


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


def _format_created_parts(value: datetime | None) -> tuple[str, str]:
    if value is None:
        return "", ""
    if value.tzinfo is not None:
        value = value.astimezone()
    return value.strftime("%d.%m.%Y"), value.strftime("%H:%M")
