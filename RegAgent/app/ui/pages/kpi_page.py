from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QShowEvent
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
from app.ui.styles import card_qss
from app.ui.theme import (
    COLOR_CONTENT_MUTED,
    KPI_STATUS_COLORS,
    MAIN_TEXT,
    app_font,
    scroll_bar_qss,
)
from app.ui.widgets.empty_state import EmptyState
from app.ui.widgets.status_chip import StatusChip


@dataclass(frozen=True)
class _LocalKpiTile:
    name: str
    fact_label: str
    plan_label: str
    frequency: str
    status: str


def _placeholder_tiles() -> list[_LocalKpiTile]:
    return [
        _LocalKpiTile("Запуски", "Факт", "План", "после первых запусков", "green"),
        _LocalKpiTile("Успешность", "Факт", "План", "после первых запусков", "yellow"),
        _LocalKpiTile("Своевременность", "Факт", "План", "после первых запусков", "green"),
        _LocalKpiTile("Ошибки", "Факт", "План", "после первых запусков", "red"),
    ]


class _PlanFactTile(QFrame):
    def __init__(self, tile: _LocalKpiTile, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("KpiTile")
        self.setStyleSheet(card_qss("KpiTile", hover=True))
        self.setMinimumHeight(188)

        accent = QFrame()
        accent.setFixedWidth(6)
        accent_color = KPI_STATUS_COLORS.get(tile.status, "rgba(16,24,23,0.12)")
        accent.setStyleSheet(
            f"background: {accent_color}; border: none; border-radius: 3px;"
        )

        name = QLabel(tile.name)
        name.setFont(app_font(16, QFont.Weight.DemiBold))
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        freq = QLabel(tile.frequency)
        freq.setFont(app_font(12))
        freq.setWordWrap(True)
        freq.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        fact_cap = QLabel(tile.fact_label)
        fact_cap.setFont(app_font(11, QFont.Weight.Medium))
        fact_cap.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        fact_val = QLabel("—")
        fact_val.setFont(app_font(28, QFont.Weight.DemiBold))
        fact_val.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        empty = QLabel("ещё нет прогонов")
        empty.setFont(app_font(12))
        empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        fact_col = QVBoxLayout()
        fact_col.setSpacing(2)
        fact_col.addWidget(fact_cap)
        fact_col.addWidget(fact_val)
        fact_col.addWidget(empty)
        fact_col.addStretch(1)

        badge = StatusChip("KPI —", variant=_chip_variant(tile.status))
        plan = QLabel(f"{tile.plan_label} —")
        plan.setFont(app_font(13, QFont.Weight.DemiBold))
        plan.setAlignment(Qt.AlignmentFlag.AlignRight)
        plan.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(badge, 0, Qt.AlignmentFlag.AlignRight)
        right.addStretch(1)
        right.addWidget(plan, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)

        values = QHBoxLayout()
        values.setSpacing(12)
        values.addLayout(fact_col, 1)
        values.addLayout(right, 0)

        header = QVBoxLayout()
        header.setSpacing(2)
        header.addWidget(name)
        header.addWidget(freq)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(accent, 0)
        inner = QVBoxLayout()
        inner.setSpacing(10)
        inner.addLayout(header)
        inner.addLayout(values, 1)
        body.addLayout(inner, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 16, 14)
        layout.addLayout(body)


def _chip_variant(status: str) -> str:
    return {"green": "success", "yellow": "warning", "red": "danger"}.get(status, "neutral")


class KpiPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._agents: list[Card] = []
        self._selected_id = ""
        self._rows: dict[str, QPushButton] = {}

        title = QLabel("KPI")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setContentsMargins(0, 0, 280, 0)
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
        list_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        list_scroll.setWidget(list_inner)
        list_scroll.setFixedWidth(300)

        self._detail_title = QLabel("Нет агентов")
        self._detail_title.setFont(app_font(22, QFont.Weight.DemiBold))
        self._detail_title.setWordWrap(True)
        self._detail_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._detail_summary = QLabel("Сначала создайте и сохраните агента из регламента.")
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
        tiles_scroll = QScrollArea()
        tiles_scroll.setWidgetResizable(True)
        tiles_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tiles_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        tiles_scroll.setWidget(tiles_wrap)

        detail = QWidget()
        detail.setStyleSheet("background: transparent;")
        detail_lay = QVBoxLayout(detail)
        detail_lay.setContentsMargins(0, 0, 0, 0)
        detail_lay.setSpacing(12)
        detail_lay.addWidget(self._detail_title)
        detail_lay.addWidget(self._detail_summary)
        detail_lay.addWidget(tiles_scroll, 1)

        body = QHBoxLayout()
        body.setSpacing(20)
        body.addWidget(list_scroll, 0)
        body.addWidget(detail, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addLayout(body, 1)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        if self._agents:
            self.refresh(list(self._agents))
        else:
            self._render_agents()
            self._clear_detail(
                "Нет агентов",
                "Сначала создайте и сохраните агента из регламента.",
            )

    def refresh(self, agents: list[Card]) -> None:
        self._agents = agents
        if self._selected_id and self._selected_id not in {item.id for item in agents}:
            self._selected_id = ""
        self._render_agents()
        if self._selected_id:
            self._show_agent(self._selected_id)
        elif agents:
            self._select_agent(agents[0].id)
        else:
            self._clear_detail(
                "Нет агентов",
                "Сначала создайте и сохраните агента из регламента.",
            )

    def _render_agents(self) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = {}
        if not self._agents:
            empty = EmptyState(
                "Нет агентов",
                "KPI появятся после создания агента.",
                glyph="◈",
            )
            self._list.addWidget(empty, 1)
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

    def _select_agent(self, card_id: str) -> None:
        self._selected_id = card_id
        for wid, row in self._rows.items():
            row.setChecked(wid == card_id)
        self._show_agent(card_id)

    def _show_agent(self, card_id: str) -> None:
        agent = next((item for item in self._agents if item.id == card_id), None)
        self._detail_title.setText(agent.title if agent else "KPI агента")
        self._detail_summary.setText(
            "RegAgent считает KPI локально после запусков. Пока история прогонов не накоплена — "
            "плитки показывают заглушки."
        )
        self._clear_tiles()
        for index, tile in enumerate(_placeholder_tiles()):
            self._tiles.addWidget(_PlanFactTile(tile), index // 2, index % 2)

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
