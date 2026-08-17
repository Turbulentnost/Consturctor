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
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentCardKpi, ApiClient, ApiError, ExecutionHistoryItem, KpiSummary
from app.ui.theme import app_font

_CARD = """
    QFrame#kpiCard {
        background: #FFFFFF;
        border: 1px solid #E4EBE8;
        border-radius: 16px;
    }
"""

_TILE_GOOD = "#1B9E6A"
_TILE_WARN = "#D4A017"
_TILE_BAD = "#D64545"
_TILE_INFO = "#08745F"
_TILE_MUTED = "#9EB5AD"


def _rate_variant(value: float, *, good: float = 0.8, warn: float = 0.6, invert: bool = False) -> str:
    if invert:
        if value <= good:
            return _TILE_GOOD
        if value <= warn:
            return _TILE_WARN
        return _TILE_BAD
    if value >= good:
        return _TILE_GOOD
    if value >= warn:
        return _TILE_WARN
    return _TILE_BAD

_GHOST = """
    QPushButton {
        background: transparent;
        color: #0F6E55;
        border: 1px solid #CFE3DC;
        border-radius: 18px;
        padding: 8px 18px;
        min-height: 34px;
    }
    QPushButton:hover { background: #F3FAF7; }
"""


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_duration(sec: float) -> str:
    if sec <= 0:
        return "—"
    if sec < 60:
        return f"{sec:.0f} сек"
    minutes = int(sec // 60)
    seconds = int(round(sec % 60))
    return f"{minutes} мин {seconds} сек" if seconds else f"{minutes} мин"


class KpiPage(QWidget):
    _data_ready = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._cards: list[AgentCardKpi] = []
        self._summary: KpiSummary | None = None
        self._agent_summaries: dict[str, KpiSummary] = {}
        self._agent_histories: dict[str, tuple[ExecutionHistoryItem, ...]] = {}
        self._data_ready.connect(self._render)

        title = QLabel("KPI")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        subtitle = QLabel(
            "Метрики из карточек агентов (platform_core.agent_cards) и агрегаты платформы."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet("color: #6B7773; background: transparent;")

        self._status = QLabel("Загрузка…")
        self._status.setFont(app_font(12))
        self._status.setStyleSheet("color: #6B7773; background: transparent;")

        refresh_btn = QPushButton("Обновить")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setStyleSheet(_GHOST)
        refresh_btn.clicked.connect(self.refresh)

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(refresh_btn)

        self._summary_widget = QWidget()
        self._summary_layout = QGridLayout(self._summary_widget)
        self._summary_layout.setContentsMargins(0, 0, 0, 0)
        self._summary_layout.setHorizontalSpacing(12)
        self._summary_layout.setVerticalSpacing(12)

        summary_title = QLabel("Сводка платформы")
        summary_title.setFont(app_font(18, QFont.Weight.DemiBold))
        summary_title.setStyleSheet("color: #101817; background: transparent;")

        cards_title = QLabel("Показатели по агентам")
        cards_title.setFont(app_font(18, QFont.Weight.DemiBold))
        cards_title.setStyleSheet("color: #101817; background: transparent;")

        self._cards_layout = QVBoxLayout()
        self._cards_layout.setSpacing(12)
        cards_widget = QWidget()
        cards_widget.setLayout(self._cards_layout)
        cards_widget.setStyleSheet("background: transparent;")

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(16)
        body_layout.addWidget(summary_title)
        body_layout.addWidget(self._summary_widget)
        body_layout.addWidget(cards_title)
        body_layout.addWidget(cards_widget)
        body_layout.addStretch(1)
        scroll.setWidget(body)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(self._status)
        layout.addLayout(top)
        layout.addWidget(scroll, 1)

    def refresh(self) -> None:
        self._status.setText("Загрузка…")
        Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            summary = self._api.kpi_summary()
            cards = self._api.list_agent_kpi_cards()
            agent_summaries: dict[str, KpiSummary] = {}
            agent_histories: dict[str, tuple[ExecutionHistoryItem, ...]] = {}
            for card in cards:
                overview = self._api.kpi_agent_overview(card.agent_id, hours=168, limit=50)
                agent_summaries[card.agent_id] = overview.summary
                agent_histories[card.agent_id] = overview.history
        except ApiError as exc:
            self._data_ready.emit(f"Ошибка: {exc.message}")
            return
        self._summary = summary
        self._cards = cards
        self._agent_summaries = agent_summaries
        self._agent_histories = agent_histories
        self._data_ready.emit(f"Обновлено: {len(cards)} агент(ов)")

    def _render(self, status: str = "") -> None:
        if status:
            self._status.setText(status)
        if status.startswith("Ошибка"):
            return
        self._render_summary()
        self._render_cards()

    def _clear_layout(self, layout: QVBoxLayout | QHBoxLayout | QGridLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _make_tile(
        self,
        *,
        icon: str,
        label: str,
        value: str,
        hint: str = "",
        accent: str = _TILE_INFO,
        badge: str = "",
        badge_accent: str = "",
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("kpiCard")
        card.setMinimumWidth(168)
        card.setMinimumHeight(118)
        card.setStyleSheet(
            _CARD
            + f" QFrame#kpiCard {{ border-left: 4px solid {accent}; border-radius: 18px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 12)
        card_layout.setSpacing(4)
        icon_label = QLabel(icon)
        icon_label.setFont(app_font(16))
        icon_label.setStyleSheet("color: #6B7773; background: transparent;")
        value_label = QLabel(value)
        value_label.setFont(app_font(26, QFont.Weight.DemiBold))
        value_label.setStyleSheet("color: #101817; background: transparent;")
        name_label = QLabel(label)
        name_label.setFont(app_font(12, QFont.Weight.DemiBold))
        name_label.setStyleSheet("color: #101817; background: transparent;")
        card_layout.addWidget(icon_label)
        card_layout.addWidget(value_label)
        card_layout.addWidget(name_label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setWordWrap(True)
            hint_label.setFont(app_font(10))
            hint_label.setStyleSheet("color: #6B7773; background: transparent;")
            card_layout.addWidget(hint_label)
        if badge:
            badge_label = QLabel(badge)
            badge_label.setFont(app_font(9, QFont.Weight.Bold))
            badge_color = badge_accent or accent
            badge_label.setStyleSheet(f"color: {badge_color}; background: transparent;")
            card_layout.addWidget(badge_label)
        return card

    def _summary_tiles(self, summary: KpiSummary) -> list[tuple[str, str, str, str, str, str, str]]:
        success_hint = (
            f"{summary.tasks_correct} из {summary.tasks_total} завершённых"
            if summary.tasks_total
            else "нет завершённых задач"
        )
        if summary.tasks_in_progress > 0:
            success_hint = f"{success_hint} · ещё {summary.tasks_in_progress} в работе"
        delta = summary.success_rate_delta
        success_badge = ""
        success_badge_accent = ""
        if delta is not None:
            arrow = "▼" if delta < 0 else "▲"
            success_badge = f"{arrow} {delta * 100:+.1f} п.п."
            if delta > 0:
                success_badge_accent = _TILE_GOOD
            elif delta < 0:
                success_badge_accent = _TILE_BAD
            else:
                success_badge_accent = _TILE_WARN
        error_hint = (
            f"{summary.tasks_failed} из {summary.tasks_total} завершённых"
            if summary.tasks_total
            else "нет завершённых задач"
        )
        return [
            ("👤", "HITL", _pct(summary.hitl_rate), "участие оператора", _rate_variant(summary.hitl_rate, good=0.15, warn=0.3, invert=True), "", ""),
            ("◎", "Успех задач", _pct(summary.task_success_rate), success_hint, _rate_variant(summary.task_success_rate), success_badge, success_badge_accent),
            ("⚠", "Доля ошибок", _pct(summary.task_error_rate), error_hint, _rate_variant(summary.task_error_rate, good=0.05, warn=0.15, invert=True), "", ""),
            ("✔", "Выполненные задачи", str(summary.completed_tasks_total), f"за период · всего {summary.tasks_lifetime_total}", _TILE_GOOD if summary.completed_tasks_total else _TILE_MUTED, "", ""),
            ("📈", "Темп", f"{summary.tasks_per_day:.1f}/день", "завершённых за период", _TILE_INFO if summary.tasks_per_day else _TILE_MUTED, "", ""),
            ("⏱", "Среднее время", _format_duration(summary.avg_execution_duration_sec), f"медиана: {_format_duration(summary.median_execution_duration_sec)}", _TILE_INFO, "", ""),
        ]

    def _render_summary(self) -> None:
        self._clear_layout(self._summary_layout)
        if self._summary is None:
            return
        tiles = self._summary_tiles(self._summary)
        cols = 3
        for index, (icon, label, value, hint, accent, badge, badge_accent) in enumerate(tiles):
            tile = self._make_tile(
                icon=icon,
                label=label,
                value=value,
                hint=hint,
                accent=accent,
                badge=badge,
                badge_accent=badge_accent,
            )
            self._summary_layout.addWidget(tile, index // cols, index % cols)

    def _render_agent_summary(self, parent_layout: QVBoxLayout, summary: KpiSummary) -> None:
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 8, 0, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        tiles = self._summary_tiles(summary)
        cols = 3
        for index, (icon, label, value, hint, accent, badge, badge_accent) in enumerate(tiles):
            tile = self._make_tile(
                icon=icon,
                label=label,
                value=value,
                hint=hint,
                accent=accent,
                badge=badge,
                badge_accent=badge_accent,
            )
            grid.addWidget(tile, index // cols, index % cols)
        parent_layout.addWidget(grid_host)

    def _render_agent_history(
        self,
        parent_layout: QVBoxLayout,
        history: tuple[ExecutionHistoryItem, ...],
    ) -> None:
        title = QLabel(f"История выполнения ({len(history)})")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")
        parent_layout.addWidget(title)
        if not history:
            empty = QLabel("История выполнения пуста")
            empty.setStyleSheet("color: #6B7773;")
            parent_layout.addWidget(empty)
            return
        for item in history:
            status_key = (item.status or "").strip().lower()
            if status_key == "error":
                status = "Ошибка"
                color = _TILE_BAD
            elif item.is_completed:
                status = "Завершён"
                color = "#6B7773"
            elif item.is_started:
                status = "В работе"
                color = "#6B7773"
            else:
                status = "Создан"
                color = "#6B7773"
            duration = _format_duration(item.duration_sec or 0) if item.is_completed else "—"
            started = item.started_at.replace("T", " ")[:16] if item.started_at else "—"
            row = QLabel(f"#{item.process_seq} · {started} · {duration} · {status}")
            row.setFont(app_font(11, QFont.Weight.DemiBold if status_key == "error" else QFont.Weight.Normal))
            row.setStyleSheet(f"color: {color}; background: transparent;")
            parent_layout.addWidget(row)

    def _render_cards(self) -> None:
        self._clear_layout(self._cards_layout)
        if not self._cards:
            empty = QLabel(
                "Карточки агентов пока не опубликованы. "
                "Завершите черновик агента (статус ready/finalized) — метрики появятся здесь."
            )
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #6B7773;")
            self._cards_layout.addWidget(empty)
            return
        for card in self._cards:
            block = QFrame()
            block.setObjectName("kpiCard")
            block.setStyleSheet(_CARD)
            block_layout = QVBoxLayout(block)
            block_layout.setContentsMargins(16, 12, 16, 12)
            title = QLabel(card.title or card.agent_id)
            title.setFont(app_font(15, QFont.Weight.DemiBold))
            title.setStyleSheet("color: #101817; background: transparent;")
            meta = QLabel(f"{card.agent_id} · {card.department or 'без отдела'}")
            meta.setFont(app_font(11))
            meta.setStyleSheet("color: #6B7773; background: transparent;")
            block_layout.addWidget(title)
            block_layout.addWidget(meta)
            agent_summary = self._agent_summaries.get(card.agent_id)
            if agent_summary is not None:
                self._render_agent_summary(block_layout, agent_summary)
            history = self._agent_histories.get(card.agent_id, ())
            self._render_agent_history(block_layout, history)
            self._cards_layout.addWidget(block)
