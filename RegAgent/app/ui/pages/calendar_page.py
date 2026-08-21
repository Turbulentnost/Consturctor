from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    QDialog,
)

from app.models import Card, ScheduledTask
from app.scheduler.logic import parse_iso, trigger_summary
from app.storage.scheduled_repository import ScheduledTaskRepository
from app.ui.styles import card_qss, ghost_button_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.schedule_task_dialog import ScheduleTaskDialog
from app.ui.widgets.status_chip import StatusChip

_MONTHS = (
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
_WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

_CARD_COLORS = (
    "#08745F",
    "#0C8A71",
    "#1A9E84",
    "#2BB896",
    "#06483D",
    "#3D8B7A",
    "#5BA898",
)


class _DayCell(QFrame):
    clicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._day: datetime | None = None
        self._in_month = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(72)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._num = QLabel("")
        self._num.setFont(app_font(12, QFont.Weight.DemiBold))
        self._dots = QHBoxLayout()
        self._dots.setContentsMargins(0, 0, 0, 0)
        self._dots.setSpacing(3)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 4, 6, 4)
        lay.setSpacing(2)
        lay.addWidget(self._num, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addLayout(self._dots)
        lay.addStretch(1)
        self._refresh_style()

    def set_day(self, day: datetime, *, in_month: bool, tasks: list[ScheduledTask]) -> None:
        self._day = day
        self._in_month = in_month
        self._num.setText(str(day.day))
        self._num.setStyleSheet(
            f"color: {'#101817' if in_month else '#B0B8B5'}; background: transparent;"
        )
        while self._dots.count():
            item = self._dots.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for task in tasks[:4]:
            dot = QLabel("●")
            dot.setFont(app_font(8))
            dot.setStyleSheet(f"color: {_color_for_card(task.card_id)}; background: transparent;")
            dot.setToolTip(task.title or task.prompt[:40])
            self._dots.addWidget(dot)
        self._refresh_style()

    def _refresh_style(self) -> None:
        bg = "#FFFFFF" if self._in_month else "#F7F9F8"
        border = "#E4EBE8" if self._in_month else "#F0F3F2"
        self.setStyleSheet(
            f"""
            QFrame {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 10px;
            }}
            QFrame:hover {{ background: #EAF7F3; border-color: #08745F; }}
            """
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._day is not None and self._in_month and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._day)
        super().mouseReleaseEvent(event)


def _color_for_card(card_id: str) -> str:
    if not card_id:
        return _CARD_COLORS[0]
    return _CARD_COLORS[hash(card_id) % len(_CARD_COLORS)]


class CalendarPage(QWidget):
    task_changed = Signal()

    def __init__(
        self,
        task_repo: ScheduledTaskRepository,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._repo = task_repo
        self._published: list[Card] = []
        self._card_titles: dict[str, str] = {}
        now = datetime.now().astimezone()
        self._year = now.year
        self._month = now.month

        title = QLabel("Календарь")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._month_label = QLabel("")
        self._month_label.setFont(app_font(18, QFont.Weight.DemiBold))
        self._month_label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        prev = QPushButton("‹")
        prev.setFixedSize(36, 36)
        prev.setStyleSheet(secondary_button_qss(radius=10, compact=True))
        prev.clicked.connect(self._prev_month)
        nxt = QPushButton("›")
        nxt.setFixedSize(36, 36)
        nxt.setStyleSheet(secondary_button_qss(radius=10, compact=True))
        nxt.clicked.connect(self._next_month)

        add_btn = QPushButton("+ Задача")
        add_btn.setStyleSheet(primary_button_qss(radius=12, compact=True))
        add_btn.clicked.connect(lambda: self._open_dialog())

        nav = QHBoxLayout()
        nav.setSpacing(8)
        nav.addWidget(prev)
        nav.addWidget(self._month_label, 1)
        nav.addWidget(nxt)
        nav.addWidget(add_btn)

        header_row = QHBoxLayout()
        for wd in _WEEKDAYS:
            lbl = QLabel(wd)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFont(app_font(11, QFont.Weight.DemiBold))
            lbl.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            header_row.addWidget(lbl, 1)

        self._grid = QGridLayout()
        self._grid.setSpacing(6)
        self._day_cells: list[_DayCell] = []

        cal_host = QWidget()
        cal_host.setStyleSheet("background: transparent;")
        cal_layout = QVBoxLayout(cal_host)
        cal_layout.setContentsMargins(0, 0, 0, 0)
        cal_layout.setSpacing(6)
        cal_layout.addLayout(header_row)
        cal_layout.addLayout(self._grid)

        cal_card = QFrame()
        cal_card.setObjectName("CalendarCard")
        cal_card.setStyleSheet(card_qss("CalendarCard", radius=16))
        cal_wrap = QVBoxLayout(cal_card)
        cal_wrap.setContentsMargins(14, 14, 14, 14)
        cal_wrap.addLayout(nav)
        cal_wrap.addWidget(cal_host)

        upcoming_title = QLabel("Ближайшие задачи")
        upcoming_title.setFont(app_font(16, QFont.Weight.DemiBold))
        upcoming_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._upcoming_list = QVBoxLayout()
        self._upcoming_list.setSpacing(8)
        upcoming_inner = QWidget()
        upcoming_inner.setLayout(self._upcoming_list)
        upcoming_scroll = QScrollArea()
        upcoming_scroll.setWidgetResizable(True)
        upcoming_scroll.setFrameShape(QFrame.Shape.NoFrame)
        upcoming_scroll.setWidget(upcoming_inner)
        upcoming_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        side = QFrame()
        side.setObjectName("UpcomingCard")
        side.setStyleSheet(card_qss("UpcomingCard", radius=16))
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(14, 14, 14, 14)
        side_lay.setSpacing(10)
        side_lay.addWidget(upcoming_title)
        side_lay.addWidget(upcoming_scroll, 1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(cal_card, 3)
        body.addWidget(side, 2)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        root.addWidget(title)
        root.addLayout(body, 1)
        self.refresh()

    def set_published_cards(self, cards: list[Card]) -> None:
        self._published = [c for c in cards if c.phase == "published"]
        self._card_titles = {c.id: c.title or c.id for c in self._published}

    def refresh(self) -> None:
        self._month_label.setText(f"{_MONTHS[self._month - 1]} {self._year}")
        self._render_grid()
        self._render_upcoming()

    def _prev_month(self) -> None:
        if self._month == 1:
            self._month = 12
            self._year -= 1
        else:
            self._month -= 1
        self.refresh()

    def _next_month(self) -> None:
        if self._month == 12:
            self._month = 1
            self._year += 1
        else:
            self._month += 1
        self.refresh()

    def _month_range(self) -> tuple[datetime, datetime]:
        start_local = datetime(self._year, self._month, 1, tzinfo=datetime.now().astimezone().tzinfo)
        if self._month == 12:
            end_local = datetime(self._year + 1, 1, 1, tzinfo=start_local.tzinfo)
        else:
            end_local = datetime(self._year, self._month + 1, 1, tzinfo=start_local.tzinfo)
        return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)

    def _tasks_for_month(self) -> list[ScheduledTask]:
        start, end = self._month_range()
        return self._repo.list_in_range(start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds"))

    def _tasks_on_day(self, day: datetime, tasks: list[ScheduledTask]) -> list[ScheduledTask]:
        tz = day.tzinfo
        day_start = day.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        out: list[ScheduledTask] = []
        for task in tasks:
            nxt = parse_iso(task.next_run_at)
            if nxt is None:
                continue
            local = nxt.astimezone(tz)
            if day_start <= local < day_end:
                out.append(task)
        return out

    def _render_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._day_cells.clear()

        tasks = self._tasks_for_month()
        tz = datetime.now().astimezone().tzinfo
        first = datetime(self._year, self._month, 1, tzinfo=tz)
        start_offset = (first.weekday()) % 7
        grid_start = first - timedelta(days=start_offset)

        for i in range(42):
            day = grid_start + timedelta(days=i)
            in_month = day.month == self._month
            cell = _DayCell()
            cell.set_day(day, in_month=in_month, tasks=self._tasks_on_day(day, tasks))
            cell.clicked.connect(self._on_day_clicked)
            self._day_cells.append(cell)
            self._grid.addWidget(cell, i // 7, i % 7)

    def _render_upcoming(self) -> None:
        while self._upcoming_list.count():
            item = self._upcoming_list.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        tasks = self._repo.list_upcoming(limit=15)
        if not tasks:
            empty = QLabel("Нет запланированных задач")
            empty.setWordWrap(True)
            empty.setFont(app_font(13))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._upcoming_list.addWidget(empty)
            self._upcoming_list.addStretch(1)
            return
        for task in tasks:
            self._upcoming_list.addWidget(self._upcoming_row(task))
        self._upcoming_list.addStretch(1)

    def _upcoming_row(self, task: ScheduledTask) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid #E4EBE8;
                border-radius: 12px;
            }
            QFrame:hover { background: #F7FBFA; border-color: #08745F; }
            """
        )
        agent = self._card_titles.get(task.card_id, task.card_id)
        title = QLabel(task.title or "Задача")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        meta = QLabel(
            f"{agent} · {trigger_summary(task)} · {_format_local(task.next_run_at)}"
        )
        meta.setWordWrap(True)
        meta.setFont(app_font(11))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        chip = StatusChip("вкл." if task.enabled else "выкл.", variant="success" if task.enabled else "neutral", compact=True)
        edit = QPushButton("Изменить")
        edit.setFlat(True)
        edit.setFont(app_font(11, QFont.Weight.DemiBold))
        edit.setStyleSheet(ghost_button_qss())
        edit.clicked.connect(lambda _=False, t=task: self._open_dialog(task=t))
        head = QHBoxLayout()
        head.addWidget(title, 1)
        head.addWidget(chip, 0)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)
        lay.addLayout(head)
        lay.addWidget(meta)
        lay.addWidget(edit, 0, Qt.AlignmentFlag.AlignRight)
        return frame

    def _on_day_clicked(self, day: object) -> None:
        if not isinstance(day, datetime):
            return
        self._open_dialog(preset_date=day.replace(hour=9, minute=0, second=0, microsecond=0))

    def open_task_dialog(
        self,
        *,
        card_id: str = "",
        preset_date: datetime | None = None,
        task: ScheduledTask | None = None,
    ) -> None:
        self._open_dialog(card_id=card_id, preset_date=preset_date, task=task)

    def _open_dialog(
        self,
        *,
        card_id: str = "",
        preset_date: datetime | None = None,
        task: ScheduledTask | None = None,
    ) -> None:
        if not self._published:
            from app.ui.widgets.app_dialog import info_dialog

            info_dialog(self, "Календарь", "Нет опубликованных агентов для планирования.")
            return
        dialog = ScheduleTaskDialog(
            published_cards=self._published,
            parent=self,
            card_id=card_id or (task.card_id if task else ""),
            preset_date=preset_date,
            task=task,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        saved = dialog.result_task()
        if saved is None:
            return
        self._repo.save(saved)
        self.refresh()
        self.task_changed.emit()


def _format_local(iso: str) -> str:
    dt = parse_iso(iso)
    if dt is None:
        return "—"
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")
