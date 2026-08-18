from __future__ import annotations

from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentKpi, ApiClient, ApiError, KpiTile, WorkflowListItem
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


_NO_RUNS = "ещё нет прогонов"
_CARD = """
QFrame#KpiTile, QFrame#KpiAgentRow {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
QFrame#KpiAgentRow:hover {
    border-color: rgba(8,116,95,0.45);
}
QFrame#KpiAgentRow[selected="true"] {
    border: 1px solid #08745F;
    background: #F3FAF7;
}
"""


def format_kpi_value(value: float | None, unit: str = "", *, empty: str = _NO_RUNS) -> str:
    if value is None:
        return empty
    if abs(value - round(value)) < 0.05:
        text = str(int(round(value)))
    else:
        text = f"{value:.1f}"
    unit = (unit or "").strip()
    return f"{text} {unit}".strip() if unit else text


class PlanFactTile(QFrame):
    def __init__(self, tile: KpiTile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KpiTile")
        self.setStyleSheet(_CARD)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        name = QLabel(tile.name or "KPI")
        name.setFont(app_font(16, QFont.Weight.DemiBold))
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        plan_cap = QLabel(tile.plan.label or "План")
        fact_cap = QLabel(tile.fact.label or "Факт")
        for cap in (plan_cap, fact_cap):
            cap.setFont(app_font(11, QFont.Weight.Medium))
            cap.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        plan_val = QLabel(format_kpi_value(tile.plan.value, tile.plan.unit, empty="—"))
        fact_val = QLabel(format_kpi_value(tile.fact.value, tile.fact.unit))
        plan_val.setFont(app_font(26, QFont.Weight.DemiBold))
        fact_val.setFont(app_font(26, QFont.Weight.DemiBold))
        plan_val.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        fact_color = "#08745F" if tile.fact.value is not None else COLOR_CONTENT_MUTED.name()
        fact_val.setWordWrap(True)
        fact_val.setStyleSheet(f"color: {fact_color}; background: transparent;")

        plan_desc = QLabel(tile.plan.description or "Как агент должен работать.")
        fact_desc = QLabel(tile.fact.description or "Что произошло по факту прогонов.")
        for desc in (plan_desc, fact_desc):
            desc.setWordWrap(True)
            desc.setFont(app_font(12))
            desc.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        cols = QHBoxLayout()
        cols.setSpacing(16)
        cols.addLayout(self._column(plan_cap, plan_val, plan_desc), 1)
        cols.addLayout(self._column(fact_cap, fact_val, fact_desc), 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(name)
        layout.addLayout(cols)

    @staticmethod
    def _column(caption: QLabel, value: QLabel, desc: QLabel) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(caption)
        col.addWidget(value)
        col.addWidget(desc)
        col.addStretch(1)
        return col


class KpiPage(QWidget):
    _agents_ready = Signal(object)
    _kpi_ready = Signal(object)
    _kpi_fail = Signal(str)

    def __init__(self, api: ApiClient | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._agents_ready.connect(self._on_agents)
        self._kpi_ready.connect(self._show_kpi)
        self._kpi_fail.connect(self._show_kpi_error)
        self._agents: list[WorkflowListItem] = []
        self._selected_id = ""
        self._rows: dict[str, QFrame] = {}

        title = QLabel("KPI")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("План — как агент должен работать. Факт — что произошло после запусков.")
        subtitle.setWordWrap(True)
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._list = QVBoxLayout()
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(8)
        list_inner = QWidget()
        list_inner.setStyleSheet("background: transparent;")
        list_inner.setLayout(self._list)
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        list_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        list_scroll.setWidget(list_inner)
        list_scroll.setFixedWidth(300)

        self._detail_title = QLabel("Выберите агента")
        self._detail_title.setFont(app_font(22, QFont.Weight.DemiBold))
        self._detail_title.setWordWrap(True)
        self._detail_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._detail_summary = QLabel("Опубликованные агенты появятся слева.")
        self._detail_summary.setWordWrap(True)
        self._detail_summary.setFont(app_font(13))
        self._detail_summary.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._tiles = QGridLayout()
        self._tiles.setContentsMargins(0, 0, 0, 0)
        self._tiles.setHorizontalSpacing(12)
        self._tiles.setVerticalSpacing(12)
        tiles_wrap = QWidget()
        tiles_wrap.setStyleSheet("background: transparent;")
        tiles_wrap.setLayout(self._tiles)

        detail_inner = QWidget()
        detail_inner.setStyleSheet("background: transparent;")
        detail_lay = QVBoxLayout(detail_inner)
        detail_lay.setContentsMargins(0, 0, 0, 0)
        detail_lay.setSpacing(12)
        detail_lay.addWidget(self._detail_title)
        detail_lay.addWidget(self._detail_summary)
        detail_lay.addWidget(tiles_wrap)
        detail_lay.addStretch(1)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        detail_scroll.setWidget(detail_inner)

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addWidget(list_scroll, 0)
        body.addWidget(detail_scroll, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addLayout(body, 1)
        self._render_agents()

    def refresh(self) -> None:
        if self._api is None:
            return

        def run() -> None:
            try:
                items = self._api.list_workflows()
            except ApiError:
                items = []
            self._agents_ready.emit(items)

        Thread(target=run, daemon=True).start()

    def _on_agents(self, items: object) -> None:
        rows = [item for item in items if isinstance(item, WorkflowListItem)] if isinstance(items, list) else []
        self._agents = [item for item in rows if item.phase == "done"]
        if self._selected_id and self._selected_id not in {item.id for item in self._agents}:
            self._selected_id = ""
        self._render_agents()
        if self._selected_id:
            self._load_kpi(self._selected_id)
        elif self._agents:
            self._select_agent(self._agents[0].id)
        else:
            self._clear_detail("Нет опубликованных агентов", "Сначала сохраните агента из паспорта и KPI.")

    def _render_agents(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = {}
        if not self._agents:
            empty = QLabel("Нет опубликованных агентов")
            empty.setWordWrap(True)
            empty.setFont(app_font(13))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._list.addWidget(empty)
            self._list.addStretch(1)
            return
        for agent in self._agents:
            row = QPushButton(agent.title or "ИИ-агент")
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setCheckable(True)
            row.setChecked(agent.id == self._selected_id)
            row.setStyleSheet(
                """
                QPushButton {
                    background: #FFFFFF; color: #101817; text-align: left;
                    border: 1px solid rgba(16,24,23,0.10); border-radius: 14px;
                    padding: 12px 14px;
                }
                QPushButton:hover { border-color: rgba(8,116,95,0.45); }
                QPushButton:checked { border: 1px solid #08745F; background: #F3FAF7; }
                """
            )
            row.setFont(app_font(13, QFont.Weight.Medium))
            row.clicked.connect(lambda _=False, wid=agent.id: self._select_agent(wid))
            self._list.addWidget(row)
            self._rows[agent.id] = row
        self._list.addStretch(1)

    def _select_agent(self, workflow_id: str) -> None:
        self._selected_id = workflow_id
        for wid, row in self._rows.items():
            if isinstance(row, QPushButton):
                row.setChecked(wid == workflow_id)
        agent = next((item for item in self._agents if item.id == workflow_id), None)
        self._detail_title.setText(agent.title if agent else "KPI агента")
        self._detail_summary.setText("Загружаю план и факт…")
        self._clear_tiles()
        self._load_kpi(workflow_id)

    def _load_kpi(self, workflow_id: str) -> None:
        if self._api is None:
            return

        def run() -> None:
            try:
                self._kpi_ready.emit(self._api.get_workflow_kpi(workflow_id))
            except ApiError as exc:
                self._kpi_fail.emit(exc.message)

        Thread(target=run, daemon=True).start()

    def _show_kpi(self, payload: object) -> None:
        if not isinstance(payload, AgentKpi):
            return
        if payload.workflow_id and payload.workflow_id != self._selected_id:
            return
        self._detail_title.setText(payload.title or self._detail_title.text())
        self._detail_summary.setText(payload.summary or "План и факт по этому агенту.")
        self._clear_tiles()
        if not payload.tiles:
            empty = QLabel("Для этого агента KPI ещё не сформированы.")
            empty.setWordWrap(True)
            empty.setFont(app_font(14))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._tiles.addWidget(empty, 0, 0)
            return
        for index, tile in enumerate(payload.tiles):
            self._tiles.addWidget(PlanFactTile(tile), index // 2, index % 2)

    def _show_kpi_error(self, message: str) -> None:
        self._clear_detail(self._detail_title.text() or "KPI агента", message or "Не удалось загрузить KPI.")

    def _clear_detail(self, title: str, summary: str) -> None:
        self._detail_title.setText(title)
        self._detail_summary.setText(summary)
        self._clear_tiles()

    def _clear_tiles(self) -> None:
        while self._tiles.count():
            item = self._tiles.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
