from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.api_client import AgentSuggestion, WorkflowListItem
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_TITLE_COL_WIDTH = 360
_DESC_COL_WIDTH = 430


class AgentImplementationPage(QWidget):
    create_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suggestions: list[AgentSuggestion] = []
        self._created_titles: set[str] = set()

        title = QLabel("ИИ-агенты для реализации")
        title.setFont(app_font(30, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setWordWrap(True)

        subtitle = QLabel("Выберите ИИ-агента из найденных функций. Все варианты сохранены в черновиках.")
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        subtitle.setWordWrap(True)

        self._list = QVBoxLayout()
        self._list.setSpacing(12)
        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        list_widget.setLayout(self._list)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(list_widget)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(scroll, 1)

    def set_suggestions(
        self,
        suggestions: list[AgentSuggestion],
        *,
        created_agents: list[WorkflowListItem] | None = None,
    ) -> None:
        self._suggestions = suggestions
        self._created_titles = {
            _normalize_title(item.title)
            for item in (created_agents or [])
            if item.title.strip()
        }
        self._render()

    def _render(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._suggestions:
            empty = QLabel("ИИ-агенты для реализации пока не найдены.")
            empty.setFont(app_font(18))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        self._list.addWidget(self._table_header())
        for suggestion in self._suggestions:
            self._list.addWidget(self._row(suggestion))
        self._list.addStretch(1)

    def _table_header(self) -> QWidget:
        header = QWidget()
        header.setStyleSheet("background: transparent;")
        layout = QGridLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setHorizontalSpacing(18)
        title = QLabel("ИИ-агент")
        description = QLabel("Описание")
        for label in (title, description):
            label.setFont(app_font(12, QFont.Weight.DemiBold))
            label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        title.setFixedWidth(_TITLE_COL_WIDTH)
        description.setFixedWidth(_DESC_COL_WIDTH)
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(QLabel(""), 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return header

    def _row(self, suggestion: AgentSuggestion) -> QWidget:
        created = _normalize_title(suggestion.title) in self._created_titles
        card = QFrame()
        card.setObjectName("ImplementationAgentRow")
        card.setStyleSheet(
            f"""
            QFrame#ImplementationAgentRow {{
                background: {'#E8F7F0' if created else '#FFFFFF'};
                border: 1px solid {'rgba(8,116,95,0.30)' if created else 'rgba(16,24,23,0.10)'};
                border-radius: 16px;
            }}
            """
        )
        layout = QGridLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(18)
        title = QLabel(suggestion.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setWordWrap(True)
        title.setFixedWidth(_TITLE_COL_WIDTH)
        description = QLabel(suggestion.description or "Функция извлечена из регламента.")
        description.setFont(app_font(12))
        description.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        description.setWordWrap(True)
        description.setFixedWidth(_DESC_COL_WIDTH)
        create = QPushButton("Создан" if created else "Создать")
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.setFixedWidth(104)
        create.setEnabled(not created)
        create.clicked.connect(lambda _checked=False, item=suggestion: self.create_requested.emit(item))
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(create, 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return card


def _normalize_title(value: str) -> str:
    return " ".join((value or "").casefold().split())
