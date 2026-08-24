from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentDraft, AgentSuggestion, BoardAgent, WorkflowBoard, WorkflowListItem
from app.ui.theme import app_font
from app.ui.widgets.run_calendar import RunCalendar, _ru_plural, _runs_word, parse_iso

# Floating shell user menu (bell + avatar + FIO) overlays the top-right content.
_USER_MENU_RESERVE = 360
_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #0A8670; }
"""
_CHIP = """
QPushButton {
    background: #FFFFFF; color: #6B7773;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 10px; padding: 0 10px;
}
QPushButton:checked { background: #EAF7F3; color: #08745F; border-color: #08745F; }
"""
_AGENTS_PANE_WIDTH = 396
_AGENT_CARD_WIDTH = 348
_TEMP = Path(__file__).resolve().parents[1] / "temp"
_TILE_QSS = """
QFrame#StatTile {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 16px;
}
"""
_STATUS = {
    "active": ("Активен", "#08745F"),
    "paused": ("Приостановлен", "#8A9692"),
    "needs_attention": ("Требует внимания", "#D64545"),
    "draft": ("Черновик", "#C47F17"),
}


def _funnel_icon(active: bool) -> QIcon:
    pix = QPixmap(36, 36)
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#08745F" if active else "#6B7773")
    painter.setPen(QPen(color, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(color)
    path = QPainterPath()
    path.moveTo(9, 10)
    path.lineTo(27, 10)
    path.lineTo(21, 19)
    path.lineTo(21, 27)
    path.lineTo(15, 29)
    path.lineTo(15, 19)
    path.closeSubpath()
    painter.drawPath(path)
    painter.end()
    return QIcon(pix)


def _load_tile_icon(name: str, size: int = 24) -> QPixmap:
    path = _TEMP / name
    if not path.exists():
        return QPixmap()
    src = QImage(str(path))
    if src.isNull():
        return QPixmap()
    img = src.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            color = QColor.fromRgba(img.pixel(x, y))
            if color.red() < 48 and color.green() < 48 and color.blue() < 48:
                color.setAlpha(0)
                img.setPixelColor(x, y, color)
    return QPixmap.fromImage(img).scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class _StatTile(QFrame):
    def __init__(self, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatTile")
        self.setStyleSheet(_TILE_QSS)
        self.setMinimumHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        icon = QLabel()
        icon.setFixedSize(24, 24)
        icon.setStyleSheet("background: transparent; border: none;")
        pix = _load_tile_icon(icon_name, 24)
        if not pix.isNull():
            icon.setPixmap(pix)
        self._text = QLabel("—")
        self._text.setFont(app_font(14, QFont.Weight.DemiBold))
        self._text.setStyleSheet("color: #08745F; background: transparent; border: none;")
        self._text.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._text.setWordWrap(False)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(10)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._text, 1)

    def set_text(self, value: str) -> None:
        self._text.setText(value)


class _FitTitleLabel(QLabel):
    """Shrink title slightly to fit one line, then wrap if still too long."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setStyleSheet("color: #101817; background: transparent; border: none;")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setWordWrap(False)
        self.setFont(app_font(13, QFont.Weight.DemiBold))

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._fit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        width = self.width()
        if width <= 8:
            return
        text = self.text() or ""
        wrap = True
        chosen = 11
        for size in (13, 12, 11):
            font = app_font(size, QFont.Weight.DemiBold)
            if QFontMetrics(font).horizontalAdvance(text) <= width:
                chosen = size
                wrap = False
                break
        if self.font().pixelSize() == chosen and self.wordWrap() == wrap:
            return
        self.setFont(app_font(chosen, QFont.Weight.DemiBold))
        self.setWordWrap(wrap)


class MyAgentsPage(QWidget):
    continue_requested = Signal(str)
    create_requested = Signal(str)
    create_suggestion_requested = Signal(str, str)
    create_agent_requested = Signal()
    delete_requested = Signal(str)
    delete_suggestion_requested = Signal(str, str)
    delete_agent_requested = Signal(str)
    stop_auto_run_requested = Signal(str)
    resume_auto_run_requested = Signal(str)
    run_agent_requested = Signal(str)
    history_requested = Signal(str, str)
    open_agent_requested = Signal(str, str)
    open_run_requested = Signal(str, str)
    schedule_requested = Signal(str)
    schedule_run_requested = Signal(str, str)
    group_runs_requested = Signal(object)
    board_range_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._drafts: list[AgentDraft] = []
        self._agents: list[WorkflowListItem] = []
        self._suggestions: list[AgentSuggestion] = []
        self._suggestion_draft_ids: dict[str, str] = {}
        self._board = WorkflowBoard()
        self._selected_id = ""
        self._search = ""
        self._status_filter = "active"

        title = QLabel("Мои агенты")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")
        subtitle = QLabel("Управляйте агентами и контролируйте их запуски")
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet("color: #6B7773; background: transparent;")
        create = QPushButton("+  Создать агента")
        create.setCursor(Qt.CursorShape.PointingHandCursor)
        create.setFixedHeight(40)
        create.setFont(app_font(13, QFont.Weight.DemiBold))
        create.setStyleSheet(_PRIMARY)
        create.clicked.connect(self.create_agent_requested.emit)
        heading = QHBoxLayout()
        heading.setContentsMargins(0, 0, _USER_MENU_RESERVE, 0)
        heading.setSpacing(12)
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(title)
        text_col.addWidget(subtitle)
        heading.addLayout(text_col, 1)
        heading.addWidget(create, 0, Qt.AlignmentFlag.AlignTop)

        self._tile_agents = _StatTile("agents.png")
        self._tile_active = _StatTile("puls.png")
        self._tile_runs = _StatTile("start.png")
        self._tile_next = _StatTile("time.png")
        stats_row = QHBoxLayout()
        stats_row.setContentsMargins(0, 0, 0, 0)
        stats_row.setSpacing(12)
        for tile in (self._tile_agents, self._tile_active, self._tile_runs, self._tile_next):
            stats_row.addWidget(tile, 1)
        self._stats_host = QWidget()
        self._stats_host.setStyleSheet("background: transparent;")
        self._stats_host.setLayout(stats_row)
        self._stats_tick = QTimer(self)
        self._stats_tick.setInterval(30000)
        self._stats_tick.timeout.connect(self._render_stats)
        self._stats_tick.start()
        self._render_stats()

        self._count = QLabel("Агенты")
        self._count.setFont(app_font(16, QFont.Weight.DemiBold))
        self._count.setStyleSheet("color: #101817; background: transparent;")
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Поиск агента")
        self._search_edit.setFixedHeight(34)
        self._search_edit.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 1px solid rgba(16,24,23,0.12); border-radius: 10px; padding: 0 10px; }"
        )
        self._search_edit.textChanged.connect(self._on_search)
        self._extra_filter = QToolButton()
        self._extra_filter.setCursor(Qt.CursorShape.PointingHandCursor)
        self._extra_filter.setFixedSize(34, 34)
        self._extra_filter.setIcon(_funnel_icon(False))
        self._extra_filter.setIconSize(QSize(18, 18))
        self._extra_filter.setProperty("filterOn", False)
        self._extra_filter.setToolTip("Фильтр: приостановленные и с ошибками")
        self._extra_filter.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._extra_filter.setStyleSheet(
            """
            QToolButton {
                background: #FFFFFF; color: #6B7773;
                border: 1px solid rgba(16,24,23,0.12); border-radius: 10px;
            }
            QToolButton:hover { background: #F4F7F6; }
            QToolButton[filterOn="true"] { background: #EAF7F3; border-color: #08745F; }
            QToolButton::menu-indicator { image: none; width: 0; }
            """
        )
        extra_menu = QMenu(self._extra_filter)
        paused_act = extra_menu.addAction("Приостановленные")
        errors_act = extra_menu.addAction("С ошибками")
        extra_menu.addSeparator()
        extra_menu.addAction("Сбросить", lambda: self._set_status_filter("active"))
        paused_act.triggered.connect(lambda: self._set_status_filter("paused"))
        errors_act.triggered.connect(lambda: self._set_status_filter("errors"))
        self._extra_filter.setMenu(extra_menu)
        search_row = QHBoxLayout()
        search_row.setSpacing(8)
        search_row.addWidget(self._search_edit, 1)
        search_row.addWidget(self._extra_filter)

        filters = QHBoxLayout()
        filters.setSpacing(6)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        for key, label in (
            ("active", "Активные"),
            ("draft", "Черновики"),
            ("all", "Все"),
        ):
            chip = QPushButton(label)
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(28)
            chip.setStyleSheet(_CHIP)
            chip.setProperty("filter_key", key)
            if key == "active":
                chip.setChecked(True)
            self._filter_group.addButton(chip)
            filters.addWidget(chip)
        self._filter_group.buttonClicked.connect(self._on_status_filter)
        filters.addStretch(1)

        self._list = QVBoxLayout()
        self._list.setSpacing(8)
        self._list.setContentsMargins(0, 0, 8, 0)
        list_host = QWidget()
        list_host.setStyleSheet("background: transparent;")
        list_host.setLayout(self._list)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(list_host)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        left = QFrame()
        left.setObjectName("AgentsPane")
        left.setStyleSheet(
            """
            QFrame#AgentsPane {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 14, 10, 14)
        left_layout.setSpacing(10)
        left_layout.addWidget(self._count)
        left_layout.addLayout(search_row)
        left_layout.addLayout(filters)
        left_layout.addWidget(scroll, 1)
        left.setFixedWidth(_AGENTS_PANE_WIDTH)
        left.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self.calendar = RunCalendar()
        self.calendar.range_changed.connect(self.board_range_changed.emit)
        self.calendar.event_clicked.connect(self.open_run_requested.emit)
        self.calendar.schedule_run_requested.connect(self.schedule_run_requested.emit)
        self.calendar.group_open_requested.connect(self.group_runs_requested.emit)
        self.calendar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        body = QHBoxLayout()
        body.setSpacing(12)
        body.addWidget(left, 0)
        body.addWidget(self.calendar, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(heading)
        layout.addWidget(self._stats_host)
        layout.addLayout(body, 1)

    def calendar_window(self) -> tuple[str, str]:
        return self.calendar.calendar_window()

    def show_agents(self) -> None:
        self._set_status_filter("active")

    def show_drafts(self) -> None:
        self._set_status_filter("draft")

    def set_board(self, board: WorkflowBoard) -> None:
        self._board = board
        self._render_stats()
        self._render_list()
        self.calendar.set_agents(board.agents)
        self.calendar.set_events(board.events)

    def set_agents(self, agents: list[WorkflowListItem]) -> None:
        self._agents = [agent for agent in agents if agent.phase == "done"]

    def set_drafts(self, drafts: list[AgentDraft]) -> None:
        self._drafts = drafts
        self._suggestions, self._suggestion_draft_ids = _collect_agent_suggestions(drafts)

    def set_agent_suggestions(self, suggestions: list[AgentSuggestion]) -> None:
        self._suggestions = suggestions
        self._suggestion_draft_ids = {}

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

    def _on_search(self, text: str) -> None:
        self._search = (text or "").strip().casefold()
        self._render_list()

    def _on_status_filter(self, button: QPushButton) -> None:
        self._set_status_filter(str(button.property("filter_key") or "active"))

    def _set_status_filter(self, key: str) -> None:
        self._status_filter = key or "active"
        extra = self._status_filter in {"paused", "errors"}
        self._filter_group.setExclusive(not extra)
        for button in self._filter_group.buttons():
            button.setChecked(button.property("filter_key") == self._status_filter)
        self._filter_group.setExclusive(True)
        self._extra_filter.setProperty("filterOn", extra)
        self._extra_filter.setIcon(_funnel_icon(extra))
        self._extra_filter.style().unpolish(self._extra_filter)
        self._extra_filter.style().polish(self._extra_filter)
        self._render_list()

    def _render_stats(self) -> None:
        stats = self._board.stats
        total = sum(1 for item in self._board.agents if item.kind == "workflow")
        self._tile_agents.set_text(f"{total} {_agents_word(total)}")
        self._tile_active.set_text(f"{stats.active_agents} {_active_word(stats.active_agents)}")
        self._tile_runs.set_text(f"{stats.runs_today} {_runs_word(stats.runs_today)} сегодня")
        self._tile_next.set_text(_next_run_tile(stats.next_run_at))

    def _visible_agents(self) -> list[BoardAgent]:
        items = list(self._board.agents)
        if self._status_filter == "active":
            items = [item for item in items if item.status == "active"]
        elif self._status_filter == "paused":
            items = [item for item in items if item.status == "paused"]
        elif self._status_filter == "errors":
            items = [item for item in items if item.status == "needs_attention" or item.last_run_status == "error"]
        elif self._status_filter == "draft":
            items = [item for item in items if item.kind == "draft"]
        if self._search:
            items = [item for item in items if self._matches_search(item)]
        return items

    def _matches_search(self, agent: BoardAgent) -> bool:
        return draft_or_agent_matches(agent, self._search, self._suggestions_for(agent))

    def _render_list(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        agents = self._visible_agents()
        self._count.setText(f"Агенты  ·  {len(agents)}")
        if not agents:
            empty = QLabel("Нет агентов по текущему фильтру.")
            empty.setWordWrap(True)
            empty.setFont(app_font(13))
            empty.setStyleSheet("color: #6B7773; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        for agent in agents:
            self._list.addWidget(self._draft_card(agent) if agent.kind == "draft" else self._agent_card(agent))
        self._list.addStretch(1)

    def _draft_for(self, agent: BoardAgent) -> AgentDraft | None:
        draft_id = (agent.draft_id or agent.id or "").strip()
        for draft in self._drafts:
            if draft.draft_id == draft_id:
                return draft
        return None

    def _suggestions_for(self, agent: BoardAgent) -> list[AgentSuggestion]:
        draft = self._draft_for(agent)
        if draft is None:
            return []
        return [item for item in (draft.agent_suggestions or []) if item.title or item.description]

    def _created_titles(self) -> set[str]:
        titles = {
            _normalize_title(item.title)
            for item in self._board.agents
            if item.kind == "workflow" and item.title.strip()
        }
        titles.update(_normalize_title(item.title) for item in self._agents if item.title.strip())
        return titles

    def _draft_card(self, agent: BoardAgent) -> QWidget:
        card = QFrame()
        card.setObjectName("AgentMiniCard")
        card.setStyleSheet(
            """
            QFrame#AgentMiniCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 14px;
            }
            """
        )
        card.setFixedWidth(_AGENT_CARD_WIDTH)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)

        icon = QLabel((agent.title or "Ч")[:1].upper())
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(36, 36)
        icon.setStyleSheet(
            "background: #EAF7F3; color: #08745F; border-radius: 10px; font-weight: 700;"
        )
        icon.setFont(app_font(16, QFont.Weight.DemiBold))

        title = _FitTitleLabel(agent.title or "Черновик агента")
        status = QLabel("●  Черновик")
        status.setFont(app_font(11, QFont.Weight.DemiBold))
        status.setStyleSheet("color: #C47F17; background: transparent; border: none;")

        menu_btn = QPushButton("⋮")
        menu_btn.setFixedSize(28, 32)
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.setStyleSheet("QPushButton { background: transparent; color: #6B7773; border: none; }")
        menu_btn.clicked.connect(lambda _=False, host=menu_btn, item=agent: self._open_menu(host, item))

        header_text = QVBoxLayout()
        header_text.setSpacing(1)
        header_text.addWidget(title)
        header_text.addWidget(status)

        header = QHBoxLayout()
        header.setSpacing(8)
        header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        header.addLayout(header_text, 1)
        header.addWidget(menu_btn, 0, Qt.AlignmentFlag.AlignTop)

        body = QVBoxLayout()
        body.setSpacing(8)
        body.addLayout(header)
        suggestions = self._suggestions_for(agent)
        if suggestions:
            label = QLabel("ИИ-агенты в черновике")
            label.setFont(app_font(11, QFont.Weight.DemiBold))
            label.setStyleSheet("color: #6B7773; background: transparent; border: none;")
            body.addWidget(label)
            created = self._created_titles()
            for item in suggestions:
                body.addWidget(self._draft_suggestion_row(agent, item, created))
        else:
            empty = QLabel("ИИ-агенты ещё не выделены. Продолжите формирование черновика.")
            empty.setWordWrap(True)
            empty.setFont(app_font(11))
            empty.setStyleSheet("color: #6B7773; background: transparent; border: none;")
            form = QPushButton("Сформировать")
            form.setCursor(Qt.CursorShape.PointingHandCursor)
            form.setFixedHeight(32)
            form.setFont(app_font(12, QFont.Weight.DemiBold))
            form.setStyleSheet(_PRIMARY)
            form.clicked.connect(
                lambda _=False, draft_id=agent.draft_id or agent.id: self.continue_requested.emit(draft_id)
            )
            body.addWidget(empty)
            body.addWidget(form)

        root = QVBoxLayout(card)
        root.setContentsMargins(10, 8, 8, 10)
        root.setSpacing(0)
        root.addLayout(body)
        return card

    def _draft_suggestion_row(
        self,
        agent: BoardAgent,
        suggestion: AgentSuggestion,
        created_titles: set[str],
    ) -> QWidget:
        created = _normalize_title(suggestion.title) in created_titles
        row_card = QFrame()
        row_card.setObjectName("DraftAgentRow")
        row_card.setStyleSheet(
            """
            QFrame#DraftAgentRow {
                background: #F7FBFA;
                border: 1px solid rgba(16,24,23,0.06);
                border-radius: 10px;
            }
            """
        )
        name = QLabel(suggestion.title or "ИИ-агент")
        name.setFont(app_font(12, QFont.Weight.DemiBold))
        name.setStyleSheet("color: #101817; background: transparent; border: none;")
        name.setWordWrap(True)
        desc = QLabel(suggestion.description or "Функция из регламента")
        desc.setFont(app_font(11))
        desc.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        desc.setWordWrap(True)
        form = QPushButton("Сформирован" if created else "Сформировать")
        form.setCursor(Qt.CursorShape.PointingHandCursor)
        form.setFixedHeight(30)
        form.setFont(app_font(12, QFont.Weight.DemiBold))
        form.setStyleSheet(_PRIMARY)
        form.setEnabled(not created)
        form.clicked.connect(
            lambda _=False, draft_id=agent.draft_id or agent.id, agent_id=suggestion.agent_id: (
                self.create_suggestion_requested.emit(draft_id, agent_id)
            )
        )
        col = QVBoxLayout(row_card)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(4)
        col.addWidget(name)
        col.addWidget(desc)
        col.addWidget(form)
        return row_card

    def _agent_card(self, agent: BoardAgent) -> QWidget:
        selected = agent.id == self._selected_id and agent.kind == "workflow"
        card = QFrame()
        card.setObjectName("AgentMiniCard")
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        border = "#08745F" if selected else "rgba(16,24,23,0.10)"
        bg = "#F3FAF7" if selected else "#FFFFFF"
        card.setStyleSheet(
            f"""
            QFrame#AgentMiniCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 14px;
            }}
            """
        )
        card.setMinimumHeight(108)
        card.setFixedWidth(_AGENT_CARD_WIDTH)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        card.mousePressEvent = lambda event, agent_id=agent.id, kind=agent.kind: self._on_select(agent_id, kind)  # type: ignore[method-assign]

        icon = QLabel((agent.title or "А")[:1].upper())
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(36, 36)
        icon.setStyleSheet(
            "background: #EAF7F3; color: #08745F; border-radius: 10px; font-weight: 700;"
        )
        icon.setFont(app_font(16, QFont.Weight.DemiBold))

        title = _FitTitleLabel(agent.title or "ИИ-агент")
        desc = QLabel(agent.description or " ")
        desc.setFont(app_font(11))
        desc.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        desc.setWordWrap(False)
        status_text, status_color = _STATUS.get(agent.status, ("Активен", "#08745F"))
        status = QLabel(f"●  {status_text}")
        status.setFont(app_font(11, QFont.Weight.DemiBold))
        status.setStyleSheet(f"color: {status_color}; background: transparent; border: none;")
        last_line = _run_line("Последний запуск", agent.last_run_at) if agent.kind == "workflow" else "Черновик"
        next_line = agent.next_run_label or _run_line("Следующий", agent.next_run_at)
        meta = QLabel(f"{last_line}\n{next_line}")
        meta.setFont(app_font(10))
        meta.setStyleSheet("color: #6B7773; background: transparent; border: none;")

        run = QPushButton("▶")
        run.setFixedSize(32, 32)
        run.setCursor(Qt.CursorShape.PointingHandCursor)
        run.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none; border-radius: 16px; }"
            "QPushButton:disabled { background: #C5DDD6; }"
        )
        run.setEnabled(agent.kind == "workflow")
        run.clicked.connect(lambda _=False, workflow_id=agent.id: self.run_agent_requested.emit(workflow_id))
        menu_btn = QPushButton("⋮")
        menu_btn.setFixedSize(28, 32)
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.setStyleSheet("QPushButton { background: transparent; color: #6B7773; border: none; }")
        menu_btn.clicked.connect(lambda _=False, host=menu_btn, item=agent: self._open_menu(host, item))

        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(title)
        text.addWidget(desc)
        text.addWidget(status)
        text.addWidget(meta)
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 8, 8, 8)
        row.setSpacing(8)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        row.addWidget(run, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(menu_btn, 0, Qt.AlignmentFlag.AlignTop)
        return card

    def _on_select(self, agent_id: str, kind: str) -> None:
        if kind != "workflow":
            return
        if self._selected_id == agent_id:
            self._selected_id = ""
            self.calendar.set_agent_filter("")
        else:
            self._selected_id = agent_id
            self.calendar.set_agent_filter(agent_id)
        self._render_list()

    def _open_menu(self, host: QWidget, agent: BoardAgent) -> None:
        menu = QMenu(self)
        if agent.kind == "draft":
            menu.addAction("Продолжить", lambda: self.continue_requested.emit(agent.draft_id or agent.id))
            menu.addAction("Удалить", lambda: self.delete_requested.emit(agent.draft_id or agent.id))
            menu.exec(host.mapToGlobal(host.rect().bottomLeft()))
            return
        menu.addAction("Открыть агента", lambda: self.open_agent_requested.emit(agent.id, agent.title))
        menu.addAction("Изменить", lambda: self.open_agent_requested.emit(agent.id, agent.title))
        menu.addAction("Посмотреть историю", lambda: self.history_requested.emit(agent.id, agent.title))
        menu.addAction("Изменить расписание", lambda: self.schedule_requested.emit(agent.id))
        if agent.paused:
            menu.addAction("Возобновить", lambda: self.resume_auto_run_requested.emit(agent.id))
        else:
            menu.addAction("Приостановить", lambda: self.stop_auto_run_requested.emit(agent.id))
        menu.addSeparator()
        menu.addAction("Удалить", lambda: self.delete_agent_requested.emit(agent.id))
        menu.exec(host.mapToGlobal(host.rect().bottomLeft()))


def draft_or_agent_matches(agent: BoardAgent, needle: str, suggestions: list[AgentSuggestion]) -> bool:
    text = (needle or "").strip().casefold()
    if not text:
        return True
    if text in (agent.title or "").casefold() or text in (agent.description or "").casefold():
        return True
    if agent.kind != "draft":
        return False
    return any(
        text in (item.title or "").casefold() or text in (item.description or "").casefold()
        for item in suggestions
    )


def _normalize_title(value: str) -> str:
    return " ".join((value or "").casefold().split())


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


def _run_line(prefix: str, value: str) -> str:
    stamp = parse_iso(value)
    if stamp is None:
        return f"{prefix}: не было"
    return f"{prefix}: {_human_when(stamp)}"


def _agents_word(n: int) -> str:
    return _ru_plural(n, "агент", "агента", "агентов")


def _active_word(n: int) -> str:
    return _ru_plural(n, "активен", "активны", "активны")


def _next_run_tile(value: str) -> str:
    stamp = parse_iso(value)
    if stamp is None:
        return "Ближайший – нет"
    local = stamp.astimezone()
    now = datetime.now().astimezone()
    if local <= now:
        return "Ближайший – сейчас"
    if local.date() == now.date():
        return f"Ближайший – {local.strftime('%H:%M')}"
    if local.date() == now.date() + timedelta(days=1):
        return f"Ближайший – завтра, {local.strftime('%H:%M')}"
    return f"Ближайший – {local.strftime('%d.%m, %H:%M')}"


def _human_when(stamp: datetime) -> str:
    now = datetime.now().astimezone()
    local = stamp.astimezone()
    if local.date() == now.date():
        return f"сегодня, {local.strftime('%H:%M')}"
    if local.date() == now.date() + timedelta(days=1):
        return f"завтра, {local.strftime('%H:%M')}"
    return local.strftime("%d.%m.%Y, %H:%M")
