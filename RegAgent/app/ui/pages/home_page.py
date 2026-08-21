from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.models import Card
from app.ui.styles import card_qss, icon_button_qss, primary_button_qss, tab_link_qss
from app.ui.theme import (
    COLOR_CONTENT_MUTED,
    ICON_DOWNLOAD,
    ICON_GEAR,
    ICON_HISTORY,
    ICON_TRASH,
    MAIN_TEXT,
    NERD_FAMILY,
    app_font,
    nerd_font,
    scroll_bar_qss,
)
from app.ui.widgets.empty_state import EmptyState
from app.ui.widgets.status_chip import StatusChip


class _ClickCard(QFrame):
    clicked = Signal()

    def __init__(self, object_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(card_qss(object_name, hover=True))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class HomePage(QWidget):
    open_requested = Signal(str)
    create_requested = Signal()
    delete_requested = Signal(str)
    continue_requested = Signal(str)
    history_requested = Signal(str, str)
    export_requested = Signal(str)
    settings_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._agents: list[Card] = []
        self._drafts: list[Card] = []
        self._schedule_counts: dict[str, int] = {}
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
        self._list.setSpacing(10)
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

    def set_cards(
        self,
        agents: list[Card],
        drafts: list[Card] | None = None,
        *,
        schedule_counts: dict[str, int] | None = None,
    ) -> None:
        self._agents = agents
        self._drafts = drafts or []
        self._schedule_counts = schedule_counts or {}
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
        for card in self._drafts:
            self._list.addWidget(self._draft_card(card))
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
        for card in self._agents:
            self._list.addWidget(self._agent_card(card))
        self._list.addStretch(1)

    def _agent_card(self, card: Card) -> QWidget:
        frame = _ClickCard("PublishedAgentRow")
        frame.clicked.connect(lambda cid=card.id: self.open_requested.emit(cid))
        frame.setToolTip("Открыть чат агента")

        title = QLabel(card.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setWordWrap(True)

        chip = StatusChip("опубликован", variant="success", compact=True)
        sched_count = self._schedule_counts.get(card.id, 0)
        if sched_count:
            chip_sched = StatusChip(f"⏱ {sched_count}", variant="neutral", compact=True)
            chip_sched.setToolTip("Запланированных задач")
        else:
            chip_sched = None

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        head.addWidget(title, 1)
        head.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)
        if chip_sched is not None:
            head.addWidget(chip_sched, 0, Qt.AlignmentFlag.AlignTop)

        meta = QLabel(_agent_meta(card))
        meta.setFont(app_font(12))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        meta.setWordWrap(True)
        meta.setToolTip(card.summary or "")

        icons = QHBoxLayout()
        icons.setContentsMargins(0, 0, 0, 0)
        icons.setSpacing(2)
        icons.addStretch(1)
        icons.addWidget(
            _icon_btn(
                ICON_GEAR,
                "Настройки",
                lambda cid=card.id: self.settings_requested.emit(cid),
            )
        )
        download = _icon_btn(
            ICON_DOWNLOAD,
            "Выгрузить регламент",
            lambda cid=card.id: self.export_requested.emit(cid),
        )
        download.setEnabled(_can_export(card))
        icons.addWidget(download)
        icons.addWidget(
            _icon_btn(
                ICON_HISTORY,
                "История запросов",
                lambda cid=card.id, name=card.title: self.history_requested.emit(
                    cid, name or "ИИ-агент"
                ),
            )
        )
        icons.addWidget(
            _icon_btn(
                ICON_TRASH,
                "Удалить",
                lambda cid=card.id: self.delete_requested.emit(cid),
                danger=True,
            )
        )

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 14, 14, 14)
        layout.setSpacing(6)
        layout.addLayout(head)
        layout.addWidget(meta)
        layout.addLayout(icons)
        return frame

    def _draft_card(self, card: Card) -> QWidget:
        frame = _ClickCard("AgentDraftRow")
        frame.clicked.connect(lambda cid=card.id: self.continue_requested.emit(cid))
        frame.setToolTip("Продолжить создание")

        title = QLabel(card.title or "ИИ-агент")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setWordWrap(True)

        chip = StatusChip(_phase_label(card.phase), variant="warning", compact=True)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(10)
        head.addWidget(title, 1)
        head.addWidget(chip, 0, Qt.AlignmentFlag.AlignTop)

        summary = " ".join((card.summary or "Продолжите настройку агента").split())
        if len(summary) > 120:
            summary = summary[:120].rsplit(" ", 1)[0] + "…"
        meta = QLabel(summary)
        meta.setFont(app_font(12))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        meta.setWordWrap(True)

        continue_btn = QPushButton("Продолжить")
        continue_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        continue_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        continue_btn.setStyleSheet(primary_button_qss(radius=10, compact=True))
        continue_btn.clicked.connect(lambda _=False, cid=card.id: self.continue_requested.emit(cid))

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 4, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(continue_btn, 0)
        actions.addStretch(1)
        actions.addWidget(
            _icon_btn(
                ICON_TRASH,
                "Удалить",
                lambda cid=card.id: self.delete_requested.emit(cid),
                danger=True,
            )
        )

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 14, 14, 14)
        layout.setSpacing(6)
        layout.addLayout(head)
        layout.addWidget(meta)
        layout.addLayout(actions)
        return frame


def _icon_btn(glyph: str, tooltip: str, handler, *, danger: bool = False) -> QToolButton:
    btn = QToolButton()
    btn.setText(glyph)
    btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setFixedSize(36, 36)
    btn.setFont(nerd_font(16))
    btn.setStyleSheet(icon_button_qss(danger=danger))
    btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    btn.clicked.connect(lambda *args: handler())
    _ = NERD_FAMILY
    return btn


def resolve_regulation_file(card: Card) -> Path | None:
    raw = (card.regulation_path or "").strip()
    if raw:
        path = Path(raw)
        if path.is_file():
            return path
    try:
        from app.config import REGULATIONS_DIR

        folder = REGULATIONS_DIR / card.id
        if folder.is_dir():
            files = sorted(
                path
                for path in folder.iterdir()
                if path.is_file() and not path.name.startswith(".")
            )
            if files:
                return files[0]
    except OSError:
        pass
    return None


def _can_export(card: Card) -> bool:
    return resolve_regulation_file(card) is not None or bool((card.regulation_text or "").strip())


def _agent_meta(card: Card) -> str:
    parts: list[str] = []
    doc = Path(card.regulation_path).name if card.regulation_path else ""
    if doc:
        parts.append(doc)
    stamp = _format_dt(card.updated_at)
    if stamp:
        parts.append(stamp)
    return " · ".join(parts) or "Нажмите, чтобы открыть чат"


def _phase_label(phase: str) -> str:
    labels = {
        "intake": "загрузка",
        "review": "проверка",
        "functions": "функции",
        "readiness": "уточнения",
        "passport": "паспорт",
        "design": "playbook",
        "demo": "демо",
        "schedule": "расписание",
        "failed": "ошибка",
    }
    return labels.get(phase, "черновик")


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
