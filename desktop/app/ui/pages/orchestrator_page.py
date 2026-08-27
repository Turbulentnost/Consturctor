from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.api_client import BoardAgent
from app.orchestrator.agents import bound_workflow_id
from app.orchestrator.engine import counts
from app.orchestrator.kpi import format_percent, has_position_kpi, score_rows, weighted_score
from app.orchestrator.models import DEFINITIONS, ProcessDefinition, ProcessInstance
from app.orchestrator.store import load_instances
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_USER_MENU_RESERVE = 360

_CARD = """
QFrame#OrchCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
"""
_BADGE = """
QLabel#OrchBadge {
    background: #EAF7F3;
    color: #08745F;
    border: 1px solid rgba(8,116,95,0.28);
    border-radius: 10px;
    padding: 4px 10px;
}
"""
_STATUS = """
QLabel#OrchStatus {
    background: #EEF7F3;
    color: #06483D;
    border-radius: 8px;
    padding: 3px 8px;
}
"""
_START_BTN = """
QPushButton {
    background: #08745F;
    color: #FFFFFF;
    border: none;
    border-radius: 12px;
    padding: 0 18px;
}
QPushButton:hover { background: #0A8A70; }
QPushButton:pressed { background: #06483D; }
"""


class OrchestratorPage(QWidget):
    run_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._user_id = "local"
        self._user_fio = ""
        self._bound_agents: list[BoardAgent] = []
        title = QLabel("Оркестратор")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        badge = QLabel("Пилот · 2 агента")
        badge.setObjectName("OrchBadge")
        badge.setFont(app_font(12, QFont.Weight.Medium))
        badge.setStyleSheet(_BADGE)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, _USER_MENU_RESERVE, 0)
        header.setSpacing(12)
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(badge, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)

        today = QLabel("Сегодня")
        today.setFont(app_font(16, QFont.Weight.DemiBold))
        today.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._chip_waiting = self._chip("Ждут меня", "0")
        self._chip_active = self._chip("Активные", "0")
        self._chip_errors = self._chip("Ошибки", "0")
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(12)
        chips.addWidget(self._chip_waiting, 1)
        chips.addWidget(self._chip_active, 1)
        chips.addWidget(self._chip_errors, 1)

        self._cards = QVBoxLayout()
        self._cards.setContentsMargins(0, 0, 0, 0)
        self._cards.setSpacing(12)

        note = QLabel("Запуск открывает опубликованного агента и выполняет его рабочую задачу.")
        note.setWordWrap(True)
        note.setFont(app_font(13))
        note.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(16)
        inner_lay.addWidget(today)
        inner_lay.addLayout(chips)
        self._kpi_title = QLabel("KPI должности")
        self._kpi_title.setFont(app_font(16, QFont.Weight.DemiBold))
        self._kpi_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._kpi_score = QLabel("")
        self._kpi_score.setFont(app_font(13, QFont.Weight.Medium))
        self._kpi_score.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._kpi_box = QVBoxLayout()
        self._kpi_box.setContentsMargins(0, 0, 0, 0)
        self._kpi_box.setSpacing(8)

        inner_lay.addLayout(self._cards)
        inner_lay.addWidget(self._kpi_title)
        inner_lay.addWidget(self._kpi_score)
        inner_lay.addLayout(self._kpi_box)
        inner_lay.addWidget(note)
        inner_lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        scroll.setWidget(inner)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(scroll, 1)
        self.refresh()

    def set_user(self, user_id: str, fio: str = "") -> None:
        self._user_id = user_id or "local"
        self._user_fio = fio or ""
        self.refresh()

    def set_bound_agents(self, agents: list[BoardAgent] | None) -> None:
        self._bound_agents = [item for item in (agents or []) if item.kind == "workflow"]
        self.refresh()

    def refresh(self) -> None:
        instances = load_instances(self._user_id)
        waiting, active, errors = self._today_counts(instances)
        self._set_chip(self._chip_waiting, str(waiting))
        self._set_chip(self._chip_active, str(active))
        self._set_chip(self._chip_errors, str(errors))
        while self._cards.count():
            taken = self._cards.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        for definition in DEFINITIONS:
            self._cards.addWidget(self._process_card(definition))
        self._render_kpi(instances)

    def _today_counts(self, instances: list[ProcessInstance]) -> tuple[int, int, int]:
        if self._bound_agents:
            waiting = sum(1 for item in self._bound_agents if item.status == "needs_attention")
            active = sum(1 for item in self._bound_agents if item.status == "active")
            errors = sum(1 for item in self._bound_agents if item.last_run_status == "error")
            return waiting, active, errors
        return counts(instances)

    def _render_kpi(self, instances: list[ProcessInstance]) -> None:
        show = has_position_kpi(self._user_id, self._user_fio)
        self._kpi_title.setVisible(show)
        self._kpi_score.setVisible(show)
        while self._kpi_box.count():
            taken = self._kpi_box.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        if not show:
            return
        rows = score_rows(instances)
        score = weighted_score(rows)
        self._kpi_score.setText(f"Итого: {format_percent(score)}")
        header = self._kpi_row("№", "Показатель", "Цель", "Вес", "Факт", header=True)
        self._kpi_box.addWidget(header)
        for row in rows:
            self._kpi_box.addWidget(
                self._kpi_row(
                    str(row.number),
                    row.name,
                    f"≥ {format_percent(row.target)}",
                    f"{row.weight:g}%",
                    format_percent(row.fact),
                    color=row.color,
                )
            )

    def _kpi_row(
        self,
        number: str,
        name: str,
        target: str,
        weight: str,
        fact: str,
        *,
        header: bool = False,
        color: str = "",
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("OrchCard")
        card.setStyleSheet(_CARD)
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 10, 16, 10)
        row.setSpacing(12)
        weight_font = app_font(12, QFont.Weight.DemiBold if header else QFont.Weight.Medium)
        fact_color = COLOR_CONTENT_MUTED.name() if header else (color or MAIN_TEXT.name())
        cells = (
            (number, 28),
            (name, 0),
            (target, 90),
            (weight, 56),
            (fact, 90),
        )
        for index, (text, width) in enumerate(cells):
            label = QLabel(text)
            label.setWordWrap(index == 1)
            label.setFont(weight_font)
            tone = fact_color if index == 4 else (COLOR_CONTENT_MUTED.name() if header else MAIN_TEXT.name())
            label.setStyleSheet(f"color: {tone}; background: transparent;")
            if width:
                label.setFixedWidth(width)
            row.addWidget(label, 1 if index == 1 else 0)
        return card

    def _chip(self, label: str, value: str) -> QFrame:
        card = QFrame()
        card.setObjectName("OrchCard")
        card.setStyleSheet(_CARD)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        name = QLabel(label)
        name.setObjectName("OrchChipName")
        name.setFont(app_font(12, QFont.Weight.Medium))
        name.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        number = QLabel(value)
        number.setObjectName("OrchChipValue")
        number.setFont(app_font(28, QFont.Weight.DemiBold))
        number.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(4)
        lay.addWidget(name)
        lay.addWidget(number)
        return card

    def _set_chip(self, card: QFrame, value: str) -> None:
        number = card.findChild(QLabel, "OrchChipValue")
        if number is not None:
            number.setText(value)

    def _process_card(self, definition: ProcessDefinition) -> QFrame:
        workflow_id = bound_workflow_id(definition, self._bound_agents)
        agent = next((item for item in self._bound_agents if item.id == workflow_id), None)
        status_label = "Опубликован"
        status_code = "active"
        if agent is not None:
            status_code = agent.status or "active"
            status_label = "Нужно внимание" if status_code == "needs_attention" else "Активен"
            if agent.paused:
                status_label = "Пауза"
                status_code = "paused"
        goal = ""
        if agent is not None:
            goal = agent.description or ""
        card = QFrame()
        card.setObjectName("OrchCard")
        card.setStyleSheet(_CARD)

        name = QLabel(definition.title)
        name.setFont(app_font(16, QFont.Weight.DemiBold))
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        pill = QLabel(f"{status_label} · {status_code}")
        pill.setObjectName("OrchStatus")
        pill.setFont(app_font(12, QFont.Weight.Medium))
        pill.setStyleSheet(_STATUS)

        meta = QLabel(goal or "Запуск откроет агента из «Мои агенты».")
        meta.setFont(app_font(13))
        meta.setWordWrap(True)
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        start = QPushButton("Запустить")
        start.setCursor(Qt.CursorShape.PointingHandCursor)
        start.setFixedHeight(36)
        start.setStyleSheet(_START_BTN)
        start.clicked.connect(lambda _checked=False, wid=workflow_id: self.run_requested.emit(wid))

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(8)
        actions.addWidget(start)
        actions.addStretch(1)

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(12)
        top.addWidget(name, 1)
        top.addLayout(actions, 0)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        lay.addLayout(top)
        lay.addWidget(pill, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(meta)
        return card
