from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import Card
from app.ui.styles import (
    card_qss,
    danger_button_qss,
    primary_button_qss,
    secondary_button_qss,
    tab_link_qss,
)
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.empty_state import EmptyState
from app.ui.widgets.status_chip import StatusChip

_TITLE_COL_WIDTH = 300
_DESC_COL_WIDTH = 360
_ACTION_COL_WIDTH = 160


class HomePage(QWidget):
    open_requested = Signal(str)
    create_requested = Signal()
    delete_requested = Signal(str)
    continue_requested = Signal(str)
    history_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._agents: list[Card] = []
        self._drafts: list[Card] = []
        self._active_view = "agents"

        title = QLabel("Мои агенты")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setContentsMargins(0, 0, 280, 0)

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
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

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

    def set_cards(self, agents: list[Card], drafts: list[Card] | None = None) -> None:
        self._agents = agents
        self._drafts = drafts or []
        self._update_nav_links()
        self._render()

    def _nav_link(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFont(app_font(14, QFont.Weight.DemiBold))
        button.setStyleSheet(tab_link_qss(active=False))
        return button

    def _set_view(self, view: str) -> None:
        if view not in {"agents", "drafts"}:
            return
        self._active_view = view
        self._update_nav_links()
        self._render()

    def _update_nav_links(self) -> None:
        self._agents_link.setText(f"Мои агенты ({len(self._agents)})")
        self._drafts_link.setText(f"Черновики ({len(self._drafts)})")
        self._agents_link.setStyleSheet(tab_link_qss(active=self._active_view == "agents"))
        self._drafts_link.setStyleSheet(tab_link_qss(active=self._active_view == "drafts"))

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
        if not self._drafts:
            empty = EmptyState(
                "Пока нет черновиков",
                "Незавершённые агенты появятся здесь после загрузки регламента.",
                action="Создать агента",
            )
            empty.action_clicked.connect(self.create_requested.emit)
            self._list.addWidget(empty, 1)
            return
        self._list.addWidget(self._table_header())
        for card in self._drafts:
            self._list.addWidget(self._draft_row(card))
        self._list.addStretch(1)

    def _render_agents(self) -> None:
        if not self._agents:
            empty = EmptyState(
                "Пока нет опубликованных агентов",
                "Создайте агента из регламента — он появится в этом списке.",
                action="Создать агента",
            )
            empty.action_clicked.connect(self.create_requested.emit)
            self._list.addWidget(empty, 1)
            return
        self._list.addWidget(self._table_header())
        for card in self._agents:
            self._list.addWidget(self._agent_row(card))
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
            label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        title.setFixedWidth(_TITLE_COL_WIDTH)
        description.setFixedWidth(_DESC_COL_WIDTH)
        layout.addWidget(title, 0, 0)
        layout.addWidget(description, 0, 1)
        layout.addWidget(action, 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return header

    def _draft_row(self, card: Card) -> QWidget:
        frame = QFrame()
        frame.setObjectName("AgentDraftRow")
        frame.setStyleSheet(card_qss("AgentDraftRow", hover=True))
        layout = QGridLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(18)

        title = QLabel(card.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setWordWrap(True)
        title.setFixedWidth(_TITLE_COL_WIDTH)

        status = "требует уточнений" if card.ui_spec.needs_clarification else "черновик"
        updated = _format_dt(card.updated_at)
        meta = QVBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        chip = StatusChip(status, variant="warning")
        chip.setAlignment(Qt.AlignmentFlag.AlignLeft)
        meta.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
        desc = QLabel(card.summary or "Без описания")
        desc.setFont(app_font(12))
        desc.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        desc.setWordWrap(True)
        desc.setFixedWidth(_DESC_COL_WIDTH)
        meta.addWidget(desc)
        if updated:
            stamp = QLabel(f"изменён {updated}")
            stamp.setFont(app_font(11))
            stamp.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            meta.addWidget(stamp)
        meta_wrap = QWidget()
        meta_wrap.setStyleSheet("background: transparent;")
        meta_wrap.setLayout(meta)
        meta_wrap.setFixedWidth(_DESC_COL_WIDTH)

        button = QPushButton("Создать")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(primary_button_qss(compact=True))
        button.clicked.connect(lambda _=False, cid=card.id: self.continue_requested.emit(cid))
        delete = QPushButton("Удалить")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setStyleSheet(danger_button_qss())
        delete.clicked.connect(lambda _=False, cid=card.id: self.delete_requested.emit(cid))

        layout.addWidget(title, 0, 0)
        layout.addWidget(meta_wrap, 0, 1)
        layout.addWidget(_actions_widget(button, delete, created_at=card.created_at), 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return frame

    def _agent_row(self, card: Card) -> QWidget:
        frame = QFrame()
        frame.setObjectName("PublishedAgentRow")
        frame.setStyleSheet(card_qss("PublishedAgentRow", hover=True))
        layout = QGridLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setHorizontalSpacing(18)

        title = QLabel(card.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setWordWrap(True)
        title.setFixedWidth(_TITLE_COL_WIDTH)

        doc = card.regulation_path.split("\\")[-1].split("/")[-1] if card.regulation_path else ""
        meta = QVBoxLayout()
        meta.setContentsMargins(0, 0, 0, 0)
        meta.setSpacing(6)
        chip = StatusChip("опубликован", variant="success")
        meta.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
        lines = ["Автозапуск выключен"]
        if doc:
            lines.append(f"Документ: {doc}")
        if card.updated_at:
            lines.append(f"Обновлён: {_format_dt(card.updated_at)}")
        desc = QLabel("\n".join(lines))
        desc.setFont(app_font(12))
        desc.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        desc.setWordWrap(True)
        desc.setFixedWidth(_DESC_COL_WIDTH)
        meta.addWidget(desc)
        meta_wrap = QWidget()
        meta_wrap.setStyleSheet("background: transparent;")
        meta_wrap.setLayout(meta)
        meta_wrap.setFixedWidth(_DESC_COL_WIDTH)

        run = QPushButton("Запустить")
        run.setCursor(Qt.CursorShape.PointingHandCursor)
        run.setStyleSheet(primary_button_qss(compact=True))
        run.clicked.connect(lambda _=False, cid=card.id: self.open_requested.emit(cid))

        stop = QPushButton("Остановить")
        stop.setCursor(Qt.CursorShape.PointingHandCursor)
        stop.setStyleSheet(secondary_button_qss())
        stop.setEnabled(False)
        stop.setToolTip("Автозапуск недоступен в RegAgent")

        history = QPushButton("История")
        history.setCursor(Qt.CursorShape.PointingHandCursor)
        history.setStyleSheet(secondary_button_qss())
        history.clicked.connect(
            lambda _=False, cid=card.id, name=card.title: self.history_requested.emit(
                cid, name or "ИИ-агент"
            )
        )

        delete = QPushButton("Удалить")
        delete.setCursor(Qt.CursorShape.PointingHandCursor)
        delete.setStyleSheet(danger_button_qss())
        delete.clicked.connect(lambda _=False, cid=card.id: self.delete_requested.emit(cid))

        layout.addWidget(title, 0, 0)
        layout.addWidget(meta_wrap, 0, 1)
        layout.addWidget(_actions_widget(run, stop, history, delete), 0, 2)
        layout.setColumnStretch(0, 2)
        layout.setColumnStretch(1, 3)
        return frame


def _actions_widget(*buttons: QPushButton, created_at: str | datetime | None = None) -> QWidget:
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
    stamp = _format_dt(created_at)
    if stamp:
        date_label = QLabel(stamp)
        date_label.setFont(app_font(11))
        date_label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        date_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(date_label)
    layout.addStretch(1)
    return widget


def _format_dt(value: str | datetime | None) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:16] if len(value) >= 16 else value
        value = parsed
    if getattr(value, "tzinfo", None) is not None:
        value = value.astimezone()
    return value.strftime("%d.%m.%Y %H:%M")
