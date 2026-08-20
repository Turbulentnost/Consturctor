from __future__ import annotations

from datetime import datetime, timezone
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentKpi, ApiClient, ApiError, KpiSchedule, KpiTile, WorkflowListItem
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


_NO_RUNS = "ещё нет прогонов"
_STATUS_COLORS = {
    "green": "#08745F",
    "yellow": "#C9A227",
    "red": "#C0392B",
}
_BADGE_BG = {
    "green": "#EAF7F3",
    "yellow": "#FFF8E6",
    "red": "#FFF4F4",
}
_CARD = """
QFrame#KpiTile {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
QFrame#KpiAgentRow {
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
QFrame#KpiExplainCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
"""
_BACK_BTN = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #F4F7F6; }
"""
_PLAN_FALLBACK = {
    "expected_interval": (
        "План — это норма, как часто агент должен запускаться. "
        "Её берём из расписания триггеров и паспорта агента. "
        "Если расписание или требования в паспорте не менялись, план остаётся прежним."
    ),
    "on_schedule_rate": (
        "План — это норма своевременности: какая доля запусков должна происходить вовремя. "
        "Обычно ожидаем, что все запуски укладываются в срок реакции из паспорта. "
        "План меняется только если изменили паспорт (срок реакции) или расписание триггеров. "
        "Иначе оставляем как есть."
    ),
    "runs_count": (
        "План — сколько раз агент должен запускаться за выбранный период. "
        "Число берём из расписания. Пока расписание не меняли, план не пересчитываем."
    ),
    "success_rate": (
        "План — какая доля запусков должна завершаться без ошибки. "
        "По умолчанию ожидаем, что все запуски успешны. "
        "План меняется только если в паспорте изменили, что считается успехом."
    ),
    "fail_count": (
        "План — сколько запусков допускается завершить с ошибкой. "
        "Обычно норма — ни одной ошибки. "
        "План не меняется, пока в паспорте не изменят требования к качеству."
    ),
}
_FACT_FALLBACK = {
    "expected_interval": (
        "Факт — сколько в среднем проходит времени между соседними запусками агента. "
        "Берём историю запусков, выстраиваем их по времени и смотрим промежутки. "
        "Если запусков ещё не было или их слишком мало, факт не считается — "
        "на плитке будет «ещё нет прогонов»."
    ),
    "on_schedule_rate": (
        "Факт показывает, какая доля запусков произошла вовремя. "
        "В истории запусков каждый прогон сопоставляем с событием, которое его вызвало "
        "(например, номер служебной записки). "
        "Считаем, сколько минут прошло от события до запуска. "
        "Если это время не больше плана — запуск вовремя. "
        "В расчёт входят только запуски, которые удалось связать с событием. "
        "После каждого завершённого запуска и по расписанию пересчёта факт обновляется. "
        "Если таких запусков ещё нет, факт не показываем."
    ),
    "runs_count": (
        "Факт — сколько раз агент реально запускался за выбранный период. "
        "Считаем записи в истории запусков. Если запусков ещё не было, факт не показываем."
    ),
    "success_rate": (
        "Факт — какая доля завершённых запусков прошла без ошибки. "
        "Смотрим только законченные запуски: успешные и с ошибкой. "
        "Если завершённых запусков ещё нет, факт не считается."
    ),
    "fail_count": (
        "Факт — сколько запусков завершилось ошибкой. "
        "Смотрим историю и считаем такие случаи. Если запусков ещё не было, факт не показываем."
    ),
}
_SCORE_FALLBACK = {
    "expected_interval": (
        "Оценка показывает, насколько фактический промежуток между запусками близок к плану. "
        "Чем ближе факт к плану, тем выше процент. Если запусков ещё мало, оценку не считаем."
    ),
    "on_schedule_rate": (
        "Оценка — это доля запусков, которые произошли вовремя, в процентах. "
        "Если ни одного запуска с привязкой к событию ещё не было, оценку не считаем."
    ),
    "runs_count": (
        "Оценка сравнивает число реальных запусков с планом. "
        "Если запусков столько же или больше, чем задумано, процент высокий. "
        "Пока запусков не было, оценку не считаем."
    ),
    "success_rate": (
        "Оценка — это доля успешных запусков в процентах. "
        "Если завершённых запусков ещё не было, оценку не считаем."
    ),
    "fail_count": (
        "Оценка высокая, пока ошибок не больше плана. "
        "Каждая лишняя ошибка снижает процент. Если запусков ещё не было, оценку не считаем."
    ),
}


def format_kpi_value(value: float | None, unit: str = "", *, empty: str = _NO_RUNS) -> str:
    if value is None:
        return empty
    if abs(value - round(value)) < 0.05:
        text = str(int(round(value)))
    else:
        text = f"{value:.1f}"
    unit = (unit or "").strip()
    return f"{text} {unit}".strip() if unit else text


def format_updated_at(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return "ещё не обновлялось"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return "ещё не обновлялось"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    local = parsed.astimezone()
    return f"обновлено {local.strftime('%d.%m %H:%M')}"


def format_schedule_cadence(schedule: KpiSchedule) -> str:
    if schedule.kind == "at" and schedule.at:
        return f"однократно ({schedule.at})"
    seconds = max(60, int(schedule.interval_seconds or 3600))
    if seconds < 3600:
        return f"каждые {seconds // 60} мин"
    hours = seconds / 3600
    if hours <= 1:
        return "каждый час"
    if seconds < 86400:
        value = int(hours) if hours == int(hours) else round(hours, 1)
        return f"каждые {value} ч"
    days = seconds / 86400
    if days <= 1:
        return "каждый день"
    value = int(days) if days == int(days) else round(days, 1)
    return f"каждые {value} дн"


def _schedule_key(schedule: KpiSchedule) -> str:
    if schedule.kind == "at":
        return f"at:{(schedule.at or '').strip()}"
    return f"interval:{max(60, int(schedule.interval_seconds or 3600))}"


def format_tile_frequency(tile: KpiTile) -> str:
    return format_schedule_cadence(tile.method.schedule)


def format_tiles_frequency(tiles: list[KpiTile]) -> str:
    labels: list[str] = []
    seen: set[str] = set()
    for tile in tiles:
        key = _schedule_key(tile.method.schedule)
        if key in seen:
            continue
        seen.add(key)
        labels.append(format_schedule_cadence(tile.method.schedule))
    if not labels:
        return "Частота обновления появится после методики."
    if len(labels) == 1:
        return f"Плитки обновляются {labels[0]}"
    return "Плитки обновляются: " + " · ".join(labels)


def _kind_of(tile: KpiTile) -> str:
    return (tile.measure.kind or "").strip()


def tile_plan_explanation(tile: KpiTile) -> str:
    text = (tile.method.plan_explanation or "").strip()
    if text:
        return text
    return _PLAN_FALLBACK.get(
        _kind_of(tile),
        "План — норма работы агента из паспорта и расписания. "
        "Его обновляем только если изменились требования или расписание.",
    )


def tile_fact_explanation(tile: KpiTile) -> str:
    text = (tile.method.fact_explanation or "").strip()
    if text:
        return text
    return _FACT_FALLBACK.get(
        _kind_of(tile),
        "Факт берём из истории запусков агента: смотрим, что реально произошло, "
        "и сравниваем с планом. Если запусков ещё нет, факт не считаем.",
    )


def tile_score_explanation(tile: KpiTile) -> str:
    text = (tile.method.score_explanation or "").strip()
    if text:
        return text
    green = tile.method.green_min
    yellow = tile.method.yellow_min
    body = _SCORE_FALLBACK.get(
        _kind_of(tile),
        "Оценка в процентах показывает, насколько факт совпадает с планом. "
        "Если запусков ещё не было, процент не считаем.",
    )
    return (
        f"{body} Цвет: зелёный — от {green:g} процентов и выше, "
        f"жёлтый — от {yellow:g} процентов, ниже — красный."
    )


def tile_recalc_explanation(tile: KpiTile) -> str:
    return f"Показатель пересчитывается {format_schedule_cadence(tile.method.schedule)}."


class KpiMethodView(QWidget):
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None, *, header_reserve: int = 0) -> None:
        super().__init__(parent)
        self._back = QPushButton("К показателям")
        self._back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back.setFixedHeight(36)
        self._back.setStyleSheet(_BACK_BTN)
        self._back.clicked.connect(self.back_requested.emit)

        self._title = QLabel("Как считается")
        self._title.setFont(app_font(28, QFont.Weight.DemiBold))
        self._title.setWordWrap(True)
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._subtitle = QLabel("Простыми словами — откуда берётся план и как получается факт.")
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(app_font(14))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._now = QLabel("")
        self._now.setWordWrap(True)
        self._now.setFont(app_font(13))
        self._now.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._sections = QVBoxLayout()
        self._sections.setContentsMargins(0, 0, 0, 0)
        self._sections.setSpacing(12)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(12)
        inner_lay.addWidget(self._now)
        inner_lay.addLayout(self._sections)
        inner_lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        scroll.setWidget(inner)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, max(0, header_reserve), 0)
        header.setSpacing(12)
        header.addWidget(self._title, 1)
        header.addWidget(self._back, 0, Qt.AlignmentFlag.AlignTop)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addLayout(header)
        root.addWidget(self._subtitle)
        root.addWidget(scroll, 1)

    def show_tile(self, tile: KpiTile) -> None:
        self._title.setText(tile.name or "KPI")
        plan_now = format_kpi_value(tile.plan.value, tile.plan.unit, empty="не задан")
        fact_now = format_kpi_value(tile.fact.value, tile.fact.unit)
        score_now = format_kpi_value(tile.score_percent, "%", empty="ещё нет оценки")
        self._now.setText(
            f"Сейчас: {tile.plan.label or 'план'} {plan_now} · "
            f"{tile.fact.label or 'факт'} {fact_now} · оценка {score_now}."
        )
        while self._sections.count():
            item = self._sections.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for title, body in (
            ("Как считается план", tile_plan_explanation(tile)),
            ("Как считается факт", tile_fact_explanation(tile)),
            ("Как получается оценка", tile_score_explanation(tile)),
            ("Как часто пересчитывается", tile_recalc_explanation(tile)),
        ):
            self._sections.addWidget(self._section(title, body))

    def _section(self, title: str, body: str) -> QFrame:
        card = QFrame()
        card.setObjectName("KpiExplainCard")
        card.setStyleSheet(_CARD)
        head = QLabel(title)
        head.setFont(app_font(16, QFont.Weight.DemiBold))
        head.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        text = QLabel(body)
        text.setWordWrap(True)
        text.setFont(app_font(14))
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(8)
        lay.addWidget(head)
        lay.addWidget(text)
        return card


class PlanFactTile(QFrame):
    method_requested = Signal(object)

    def __init__(self, tile: KpiTile, parent: QWidget | None = None, *, paused: bool = False) -> None:
        super().__init__(parent)
        self._tile = tile
        self._paused = paused
        self.setObjectName("KpiTile")
        self.setStyleSheet(
            """
            QFrame#KpiTile {
                background: #E6E9E8;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 16px;
            }
            """
            if paused
            else _CARD
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumHeight(188)

        accent = QFrame()
        accent.setFixedWidth(6)
        accent.setStyleSheet(
            f"background: {_STATUS_COLORS.get(tile.color, 'rgba(16,24,23,0.12)')}; border: none; border-radius: 3px;"
        )

        self._info = QToolButton()
        self._info.setText("i")
        self._info.setCursor(Qt.CursorShape.PointingHandCursor)
        self._info.setFixedSize(28, 28)
        self._info.setStyleSheet(
            "QToolButton { background: #F4F7F6; color: #06483D; border: 1px solid rgba(16,24,23,0.10);"
            " border-radius: 14px; font-weight: 600; }"
            "QToolButton:hover { background: #EAF7F3; }"
        )
        self._info.clicked.connect(self._show_method)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_front(tile))
        self._stack.addWidget(self._build_back(tile))

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(accent, 0)
        body.addWidget(self._stack, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 14, 16, 14)
        layout.setSpacing(0)
        layout.addLayout(body)

    def _build_front(self, tile: KpiTile) -> QWidget:
        color = _STATUS_COLORS.get(tile.color, MAIN_TEXT.name())
        if tile.fact.value is None:
            color = COLOR_CONTENT_MUTED.name()

        name = QLabel(tile.name or "KPI")
        name.setFont(app_font(16, QFont.Weight.DemiBold))
        name.setWordWrap(True)
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        freq = QLabel(format_tile_frequency(tile))
        freq.setFont(app_font(12))
        freq.setWordWrap(True)
        freq.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, 0, 0)
        header_text.setSpacing(2)
        header_text.addWidget(name)
        header_text.addWidget(freq)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.addLayout(header_text, 1)
        header.addWidget(self._info, 0, Qt.AlignmentFlag.AlignTop)

        fact_cap = QLabel(tile.fact.label or "Факт")
        fact_cap.setFont(app_font(11, QFont.Weight.Medium))
        fact_cap.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        fact_val = QLabel(format_kpi_value(tile.fact.value, tile.fact.unit))
        fact_val.setFont(app_font(28, QFont.Weight.DemiBold))
        fact_val.setWordWrap(True)
        fact_val.setStyleSheet(f"color: {color}; background: transparent;")

        fact_col = QVBoxLayout()
        fact_col.setSpacing(2)
        fact_col.addWidget(fact_cap)
        fact_col.addWidget(fact_val)
        fact_col.addStretch(1)

        badge_text = (
            f"{format_kpi_value(tile.score_percent, '%', empty='')} KPI"
            if tile.score_percent is not None
            else "KPI —"
        )
        badge = QLabel(badge_text)
        badge.setFont(app_font(12, QFont.Weight.DemiBold))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"color: {_STATUS_COLORS.get(tile.color, '#53625E')};"
            f" background: {_BADGE_BG.get(tile.color, '#F4F7F6')};"
            " border-radius: 8px; padding: 6px 10px;"
        )

        plan_text = format_kpi_value(tile.plan.value, tile.plan.unit, empty="—")
        plan = QLabel(f"{tile.plan.label or 'План'} {plan_text}")
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

        front = QWidget()
        front.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(front)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addLayout(header)
        lay.addLayout(values, 1)
        return front

    def _build_back(self, tile: KpiTile) -> QWidget:
        title = QLabel("Данные расчёта")
        title.setFont(app_font(14, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        updated = QLabel(format_updated_at(tile.updated_at))
        updated.setFont(app_font(12))
        updated.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        body = QLabel((tile.evidence or "").strip() or "Данных расчёта пока нет.")
        body.setWordWrap(True)
        body.setFont(app_font(12))
        body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        hint = QLabel("Нажмите плитку, чтобы вернуть.")
        hint.setFont(app_font(11))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        back = QWidget()
        back.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(back)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(title)
        lay.addWidget(updated)
        lay.addWidget(body, 1)
        lay.addWidget(hint)
        return back

    def _show_method(self) -> None:
        self.method_requested.emit(self._tile)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self._info.underMouse():
            self._stack.setCurrentIndex(1 - self._stack.currentIndex())
        super().mouseReleaseEvent(event)


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
        tiles_scroll = QScrollArea()
        tiles_scroll.setWidgetResizable(True)
        tiles_scroll.setFrameShape(QFrame.Shape.NoFrame)
        tiles_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
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

        overview = QWidget()
        overview.setStyleSheet("background: transparent;")
        overview_lay = QVBoxLayout(overview)
        overview_lay.setContentsMargins(0, 0, 0, 0)
        overview_lay.setSpacing(10)
        overview_lay.addWidget(title)
        overview_lay.addWidget(subtitle)
        overview_lay.addLayout(body, 1)

        self._method_page = KpiMethodView()
        self._method_page.back_requested.connect(self._hide_method)

        self._view = QStackedWidget()
        self._view.addWidget(overview)
        self._view.addWidget(self._method_page)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._view)
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
            if agent.paused:
                row.setText(f"{agent.title or 'ИИ-агент'} · остановлен")
                row.setStyleSheet(
                    """
                    QPushButton {
                        background: #E6E9E8; color: #7A8682; text-align: left;
                        border: 1px solid rgba(16,24,23,0.08); border-radius: 14px;
                        padding: 12px 14px;
                    }
                    QPushButton:hover { border-color: rgba(16,24,23,0.16); }
                    QPushButton:checked { border: 1px solid #9AA6A2; background: #DEE2E1; }
                    """
                )
            else:
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
        self._hide_method()
        self._selected_id = workflow_id
        for wid, row in self._rows.items():
            if isinstance(row, QPushButton):
                row.setChecked(wid == workflow_id)
        agent = next((item for item in self._agents if item.id == workflow_id), None)
        self._detail_title.setText(agent.title if agent else "KPI агента")
        self._detail_summary.setText("Загружаю частоту обновления…")
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
        agent = next((item for item in self._agents if item.id == payload.workflow_id), None)
        if agent is not None and agent.paused:
            self._detail_summary.setText("KPI приостановлены — агент остановлен.")
        else:
            self._detail_summary.setText(format_tiles_frequency(payload.tiles))
        self._clear_tiles()
        if not payload.tiles:
            empty = QLabel("Для этого агента KPI ещё не сформированы.")
            empty.setWordWrap(True)
            empty.setFont(app_font(14))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._tiles.addWidget(empty, 0, 0)
            return
        paused = bool(agent is not None and agent.paused)
        for index, tile in enumerate(payload.tiles):
            card = PlanFactTile(tile, paused=paused)
            card.method_requested.connect(self._open_method)
            self._tiles.addWidget(card, index // 2, index % 2)

    def _open_method(self, tile: object) -> None:
        if not isinstance(tile, KpiTile):
            return
        self._method_page.show_tile(tile)
        self._view.setCurrentWidget(self._method_page)

    def _hide_method(self) -> None:
        self._view.setCurrentIndex(0)

    def _show_kpi_error(self, message: str) -> None:
        self._clear_detail(self._detail_title.text() or "KPI агента", message or "Не удалось загрузить KPI.")

    def _clear_detail(self, title: str, summary: str) -> None:
        self._hide_method()
        self._detail_title.setText(title)
        self._detail_summary.setText(summary)
        self._clear_tiles()

    def _clear_tiles(self) -> None:
        while self._tiles.count():
            item = self._tiles.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
