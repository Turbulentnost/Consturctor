"""Week / day / month calendar of agent runs."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from PySide6.QtCore import QDateTime, QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.api_client import BoardAgent, CalendarEvent
from app.ui.theme import app_font

_MONTHS = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)
_MONTH_TITLE = (
    "",
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)
_DAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
_WEEKDAYS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
_STATUS_STYLE = {
    "scheduled": ("#E8F6F1", "#08745F", "Запланирован"),
    "running": ("#E8F1FB", "#2F6FED", "Выполняется"),
    "ok": ("#F7FBF9", "#5B8F7E", "Выполнен"),
    "error": ("#FDECEC", "#D64545", "Ошибка"),
    "paused": ("#F2F4F3", "#8A9692", "Приостановлен"),
}
_SOURCE_LABEL = {
    "schedule": "по расписанию",
    "manual": "вручную",
    "event": "по событию",
}
_BTN = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 10px; padding: 0 12px;
}
QPushButton:hover { background: #F4F7F6; }
QPushButton:checked { background: #08745F; color: #FFFFFF; border-color: #08745F; }
"""
_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 10px; padding: 0 14px;
}
QPushButton:hover { background: #0A8670; }
"""


class _FlowLayout(QLayout):
    """Left-to-right row that wraps to the next line instead of shrinking items."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._fill(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._fill(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margin = self.contentsMargins()
        size += QSize(margin.left() + margin.right(), margin.top() + margin.bottom())
        return size

    def _fill(self, rect: QRect, test_only: bool) -> int:
        margin = self.contentsMargins()
        area = rect.adjusted(margin.left(), margin.top(), -margin.right(), -margin.bottom())
        x = area.x()
        y = area.y()
        line_h = 0
        gap = self.spacing()
        for item in self._items:
            hint = item.sizeHint()
            next_x = x + hint.width() + gap
            if line_h and next_x - gap > area.right() + 1:
                x = area.x()
                y = y + line_h + gap
                next_x = x + hint.width() + gap
                line_h = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x = next_x
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y() + margin.bottom()


def parse_iso(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        stamp = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone()


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def format_period(view: str, anchor: date) -> str:
    if view == "day":
        return f"{anchor.day} {_MONTHS[anchor.month]} {anchor.year}"
    if view == "month":
        name = _MONTH_TITLE[anchor.month]
        return f"{name} {anchor.year}"
    start = monday_of(anchor)
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"{start.day}–{end.day} {_MONTHS[start.month]} {start.year}"
    return (
        f"{start.day} {_MONTHS[start.month]} – {end.day} {_MONTHS[end.month]} {end.year}"
    )


def window_for(view: str, anchor: date) -> tuple[datetime, datetime]:
    tz = datetime.now().astimezone().tzinfo
    if view == "day":
        start = datetime(anchor.year, anchor.month, anchor.day, tzinfo=tz)
        return start, start + timedelta(days=1)
    if view == "month":
        start = datetime(anchor.year, anchor.month, 1, tzinfo=tz)
        if anchor.month == 12:
            end = datetime(anchor.year + 1, 1, 1, tzinfo=tz)
        else:
            end = datetime(anchor.year, anchor.month + 1, 1, tzinfo=tz)
        return start, end
    start_day = monday_of(anchor)
    start = datetime(start_day.year, start_day.month, start_day.day, tzinfo=tz)
    return start, start + timedelta(days=7)


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if n % 10 in {2, 3, 4} and n % 100 not in {12, 13, 14}:
        return few
    return many


def _runs_word(n: int) -> str:
    return _ru_plural(n, "запуск", "запуска", "запусков")


def _errors_word(n: int) -> str:
    return _ru_plural(n, "ошибка", "ошибки", "ошибок")


def slot_key(event: CalendarEvent) -> tuple:
    stamp = parse_iso(event.start_at)
    if stamp is None:
        return ("none", event.id)
    return (stamp.date().isoformat(), stamp.hour)


def group_by_slot(events: list[CalendarEvent]) -> list[list[CalendarEvent]]:
    buckets: dict[tuple, list[CalendarEvent]] = {}
    order: list[tuple] = []
    for item in events:
        key = slot_key(item)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(item)
    return [sorted(buckets[key], key=lambda item: item.start_at) for key in order]


def group_heading(events: list[CalendarEvent]) -> str:
    stamp = parse_iso(events[0].start_at) if events else None
    if stamp is None:
        return "Запуски"
    return f"{_WEEKDAYS[stamp.weekday()]}, {stamp.day} {_MONTHS[stamp.month]}  ·  {stamp.strftime('%H:00')}"


def group_summary(events: list[CalendarEvent]) -> tuple[str, str, str]:
    n = len(events)
    stamp = parse_iso(events[0].start_at) if events else None
    time_text = f"{stamp.hour:02d}:00" if stamp else ""
    title = f"{time_text}  ·  {n} {_runs_word(n)}"
    errors = sum(1 for item in events if item.status == "error")
    running = sum(1 for item in events if item.status == "running")
    same_agent = len({item.workflow_id for item in events}) == 1
    if errors:
        return title, f"{errors} {_errors_word(errors)}", "#D64545"
    if running:
        return title, f"Выполняются {running} из {n}", "#2F6FED"
    if same_agent:
        return title, "История", "#6B7773"
    if all(item.status == "ok" for item in events):
        return title, "Выполнено", "#5B8F7E"
    if all(item.status == "scheduled" for item in events):
        return title, "Запланировано", "#08745F"
    return title, _STATUS_STYLE.get(events[0].status, _STATUS_STYLE["scheduled"])[2], "#6B7773"


class _EventBlock(QFrame):
    clicked = Signal(object)

    def __init__(self, event: CalendarEvent, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.item = event
        bg, border, label = _STATUS_STYLE.get(event.status, _STATUS_STYLE["scheduled"])
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            f"""
            QFrame {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            """
        )
        stamp = parse_iso(event.start_at)
        time_text = stamp.strftime("%H:%M") if stamp else ""
        title = QLabel(f"{time_text}  {event.title}")
        title.setFont(app_font(11, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent; border: none;")
        title.setWordWrap(False)
        sub = QLabel(_clip(event.subtitle or label, 42))
        sub.setFont(app_font(10))
        sub.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        layout.addWidget(title)
        layout.addWidget(sub)
        tip = [
            event.title,
            f"{time_text} · {label}",
            _SOURCE_LABEL.get(event.source, ""),
            event.subtitle,
        ]
        self.setToolTip("\n".join(part for part in tip if part))

    def mousePressEvent(self, mouse) -> None:  # noqa: N802
        self.clicked.emit(self.item)
        super().mousePressEvent(mouse)


class _GroupBlock(QWidget):
    clicked = Signal(object)

    def __init__(self, events: list[CalendarEvent], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.events = list(events)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        title, subtitle, color = group_summary(self.events)
        errors = any(item.status == "error" for item in self.events)
        card = QFrame(self)
        card.setObjectName("GroupFront")
        border = "#D64545" if errors else "#08745F"
        bg = "#FDECEC" if errors else "#E8F6F1"
        card.setStyleSheet(
            f"""
            QFrame#GroupFront {{
                background: {bg};
                border: 1px solid {border};
                border-radius: 8px;
            }}
            """
        )
        head = QLabel(title)
        head.setFont(app_font(11, QFont.Weight.DemiBold))
        head.setStyleSheet("color: #101817; background: transparent; border: none;")
        sub = QLabel(subtitle)
        sub.setFont(app_font(10))
        sub.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(0)
        layout.addWidget(head)
        layout.addWidget(sub)
        self._card = card
        self.setToolTip(f"{title}\n{subtitle}")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._card.setGeometry(0, 0, max(40, self.width() - 8), self.height())
        self._card.raise_()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipRect(self.rect())
        front = self._card.geometry()
        rear = self.events[1:3]
        for index, item in enumerate(reversed(rear), start=1):
            bg, border, _label = _STATUS_STYLE.get(item.status, _STATUS_STYLE["scheduled"])
            if item.status == "error":
                bg, border = "#FDECEC", "#D64545"
            rect = front.adjusted(index * 4, index * 2, index * 4, index * 2)
            painter.setBrush(QColor(bg))
            painter.setPen(QPen(QColor(border), 1.5))
            painter.drawRoundedRect(rect, 8, 8)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self.events)
        super().mousePressEvent(event)


class _GroupPopup(QFrame):
    event_clicked = Signal(object)
    open_all_requested = Signal(object)

    def __init__(self, events: list[CalendarEvent], parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.events = list(events)
        self.setObjectName("GroupPopup")
        self.setStyleSheet(
            """
            QFrame#GroupPopup {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.12);
                border-radius: 14px;
            }
            """
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        head = QLabel(group_heading(self.events))
        head.setFont(app_font(13, QFont.Weight.DemiBold))
        head.setStyleSheet("color: #101817; background: transparent; border: none;")
        layout.addWidget(head)
        for item in self.events:
            layout.addWidget(self._row(item))
        open_all = QPushButton("Открыть все запуски")
        open_all.setCursor(Qt.CursorShape.PointingHandCursor)
        open_all.setFlat(True)
        open_all.setFont(app_font(12, QFont.Weight.DemiBold))
        open_all.setStyleSheet(
            "QPushButton { color: #08745F; background: transparent; border: none; text-align: left; padding: 6px 0 0 0; }"
            "QPushButton:hover { color: #06483D; }"
        )
        open_all.clicked.connect(lambda: self.open_all_requested.emit(self.events))
        layout.addWidget(open_all)
        self.setFixedWidth(320)

    def _row(self, item: CalendarEvent) -> QWidget:
        row = QFrame()
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setStyleSheet("QFrame { background: transparent; border: none; }")
        icon = QLabel((item.title or "А")[:1].upper())
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(28, 28)
        icon.setStyleSheet(
            "background: #EAF7F3; color: #08745F; border-radius: 8px; border: none;"
        )
        icon.setFont(app_font(12, QFont.Weight.DemiBold))
        stamp = parse_iso(item.start_at)
        time_text = stamp.strftime("%H:%M") if stamp else ""
        name = QLabel(f"{time_text}  {item.title}".strip() if item.title else (time_text or "ИИ-агент"))
        name.setFont(app_font(12, QFont.Weight.DemiBold))
        name.setStyleSheet("color: #101817; background: transparent; border: none;")
        _bg, color, label = _STATUS_STYLE.get(item.status, _STATUS_STYLE["scheduled"])
        status = QLabel(f"●  {label}")
        status.setFont(app_font(11))
        status.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(name)
        text.addWidget(status)
        menu_btn = QPushButton("⋮")
        menu_btn.setFixedSize(24, 28)
        menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu_btn.setStyleSheet("QPushButton { background: transparent; color: #6B7773; border: none; }")
        menu_btn.clicked.connect(lambda _=False, payload=item, host=menu_btn: self._open_menu(host, payload))
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 4, 0, 4)
        box.setSpacing(8)
        box.addWidget(icon)
        box.addLayout(text, 1)
        box.addWidget(menu_btn)
        row.mousePressEvent = lambda mouse, payload=item: self._on_row(mouse, payload)  # type: ignore[method-assign]
        return row

    def _on_row(self, mouse, payload: CalendarEvent) -> None:
        if mouse.button() == Qt.MouseButton.LeftButton:
            self.event_clicked.emit(payload)
            self.close()

    def _open_menu(self, host: QWidget, payload: CalendarEvent) -> None:
        menu = QMenu(self)
        menu.addAction("Открыть", lambda: self._pick(payload))
        menu.addAction("История", lambda: self._pick(payload))
        menu.exec(host.mapToGlobal(host.rect().bottomLeft()))

    def _pick(self, event: CalendarEvent) -> None:
        self.event_clicked.emit(event)
        self.close()


class _WeekGrid(QWidget):
    event_clicked = Signal(object)
    group_clicked = Signal(object)
    _COL_MIN = 168
    _HEADER = 54

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._days: list[date] = []
        self._events: list[CalendarEvent] = []
        self._blocks: list[QWidget] = []
        self._start_hour = 8
        self._end_hour = 20
        self._hour_h = 56
        self._gutter = 52
        self.setMinimumHeight(12 * 56)
        self.setSizePolicy(QSizePolicy.Policy.MinimumExpanding, QSizePolicy.Policy.MinimumExpanding)

    def _day_count(self) -> int:
        return max(1, len(self._days) or 7)

    def _min_width(self) -> int:
        return self._gutter + self._day_count() * self._COL_MIN

    def _col_w(self) -> float:
        return float(self._COL_MIN)

    def set_data(self, days: list[date], events: list[CalendarEvent]) -> None:
        self._days = days
        self._events = events
        event_hours: list[int] = []
        for item in events:
            stamp = parse_iso(item.start_at)
            if stamp is None:
                continue
            event_hours.append(stamp.hour)
        self._start_hour = min([8, *event_hours])
        self._end_hour = max([20, *(hour + 1 for hour in event_hours)])
        self._end_hour = min(24, max(self._end_hour, self._start_hour + 1))
        self.setMinimumWidth(self._min_width())
        self.setFixedWidth(self._min_width())
        self._rebuild()
        self.update()

    def time_y(self, stamp: datetime) -> int:
        minutes = (stamp.hour - self._start_hour) * 60 + stamp.minute
        return self._HEADER + int(minutes / 60 * self._hour_h)

    def today_x(self) -> int:
        today = date.today()
        if today not in self._days:
            return 0
        return int(self._gutter + self._days.index(today) * self._col_w())

    def _hour_count(self) -> int:
        return max(1, self._end_hour - self._start_hour)

    def sizeHint(self):  # noqa: N802
        return QSize(self._min_width(), self._HEADER + self._hour_count() * self._hour_h)

    def minimumSizeHint(self):  # noqa: N802
        return self.sizeHint()

    def _rebuild(self) -> None:
        for block in self._blocks:
            block.deleteLater()
        self._blocks = []
        for group in group_by_slot(self._events):
            if len(group) == 1:
                block = _EventBlock(group[0], self)
                block.clicked.connect(self.event_clicked.emit)
            else:
                block = _GroupBlock(group, self)
                block.clicked.connect(self.group_clicked.emit)
            self._blocks.append(block)
        self._layout_blocks()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_blocks()

    def _layout_blocks(self) -> None:
        if not self._days:
            return
        col_w = self._col_w()
        header = self._HEADER
        for block in self._blocks:
            event = getattr(block, "item", None)
            events = getattr(block, "events", None)
            sample = event if isinstance(event, CalendarEvent) else (events[0] if events else None)
            stamp = parse_iso(sample.start_at) if sample is not None else None
            if stamp is None:
                block.hide()
                continue
            day = stamp.date()
            try:
                index = self._days.index(day)
            except ValueError:
                block.hide()
                continue
            minutes = (stamp.hour - self._start_hour) * 60
            y = header + int(minutes / 60 * self._hour_h) + 4
            x = int(self._gutter + index * col_w) + 4
            block.setGeometry(QRect(x, y, max(72, int(col_w) - 10), min(46, self._hour_h - 8)))
            block.show()
            block.raise_()
        self.setFixedHeight(header + self._hour_count() * self._hour_h)
        self.setFixedWidth(self._min_width())

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        if not self._days:
            return
        col_w = self._col_w()
        header = self._HEADER
        today = date.today()
        now = datetime.now().astimezone()
        for index, day in enumerate(self._days):
            x = self._gutter + index * col_w
            if day == today:
                painter.fillRect(QRect(int(x), 0, int(col_w), self.height()), QColor("#F3FAF7"))
        painter.setPen(QPen(QColor(16, 24, 23, 28)))
        for hour in range(self._start_hour, self._end_hour + 1):
            y = header + (hour - self._start_hour) * self._hour_h
            painter.drawLine(int(self._gutter), y, int(self._gutter + len(self._days) * col_w), y)
            painter.setFont(app_font(10))
            painter.setPen(QColor("#8A9692"))
            painter.drawText(QRect(0, y - 8, self._gutter - 6, 16), Qt.AlignmentFlag.AlignRight, f"{hour:02d}:00")
            painter.setPen(QPen(QColor(16, 24, 23, 28)))
        for index, day in enumerate(self._days):
            x = self._gutter + index * col_w
            painter.setPen(QPen(QColor(16, 24, 23, 28)))
            painter.drawLine(int(x), 0, int(x), self.height())
            count = sum(1 for item in self._events if (parse_iso(item.start_at) or datetime.min).date() == day)
            label = f"{_DAYS[day.weekday()]} {day.day}"
            font = app_font(11, QFont.Weight.DemiBold)
            painter.setFont(font)
            if day == today:
                metrics = QFontMetrics(font)
                pill_w = min(int(col_w) - 8, max(56, metrics.horizontalAdvance(label) + 18))
                pill_h = 26
                pill_x = int(x + (col_w - pill_w) / 2)
                painter.setBrush(QColor("#08745F"))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(QRect(pill_x, 8, pill_w, pill_h), 13, 13)
                painter.setPen(QColor("#FFFFFF"))
                painter.drawText(QRect(pill_x, 8, pill_w, pill_h), Qt.AlignmentFlag.AlignCenter, label)
            else:
                painter.setPen(QColor("#101817"))
                painter.drawText(
                    QRect(int(x), 8, int(col_w), 26),
                    Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                    label,
                )
            if count:
                painter.setPen(QColor("#5B8F7E" if day == today else "#8A9692"))
                painter.setFont(app_font(9))
                painter.drawText(
                    QRect(int(x), 36, int(col_w), 16),
                    Qt.AlignmentFlag.AlignHCenter,
                    str(count),
                )
            if day == today and self._start_hour <= now.hour <= self._end_hour:
                minutes = (now.hour - self._start_hour) * 60 + now.minute
                y = header + int(minutes / 60 * self._hour_h)
                painter.setPen(QPen(QColor("#08745F"), 2))
                painter.drawLine(int(x), y, int(x + col_w), y)


class _MonthGrid(QWidget):
    event_clicked = Signal(object)
    group_clicked = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        self._body = QWidget()
        self._grid = None
        self._layout.addWidget(self._body)

    def set_data(self, anchor: date, events: list[CalendarEvent]) -> None:
        from PySide6.QtWidgets import QGridLayout

        old = self._body
        self._body = QWidget()
        grid = QGridLayout(self._body)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(6)
        for index, name in enumerate(_DAYS):
            label = QLabel(name)
            label.setFont(app_font(11, QFont.Weight.DemiBold))
            label.setStyleSheet("color: #6B7773; background: transparent;")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(label, 0, index)
        first = date(anchor.year, anchor.month, 1)
        start = monday_of(first)
        today = date.today()
        for cell in range(42):
            day = start + timedelta(days=cell)
            frame = QFrame()
            in_month = day.month == anchor.month
            is_today = day == today
            bg = "#F3FAF7" if is_today else "#FFFFFF"
            border = "#08745F" if is_today else "rgba(16,24,23,0.08)"
            frame.setStyleSheet(
                f"QFrame {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}"
            )
            frame.setMinimumHeight(88)
            col = QVBoxLayout(frame)
            col.setContentsMargins(8, 6, 8, 6)
            col.setSpacing(3)
            head = QLabel(str(day.day))
            head.setFont(app_font(12, QFont.Weight.DemiBold))
            color = "#08745F" if is_today else ("#101817" if in_month else "#B4BDB9")
            head.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            col.addWidget(head)
            day_events = [
                item
                for item in events
                if (parse_iso(item.start_at) or datetime.min).date() == day
            ]
            chips = 0
            for group in group_by_slot(day_events):
                if chips >= 3:
                    break
                if len(group) == 1:
                    chip = _EventBlock(group[0])
                    chip.setMaximumHeight(36)
                    chip.clicked.connect(self.event_clicked.emit)
                else:
                    chip = _GroupBlock(group)
                    chip.setMaximumHeight(42)
                    chip.clicked.connect(self.group_clicked.emit)
                col.addWidget(chip)
                chips += 1
            leftover = len(group_by_slot(day_events)) - chips
            if leftover > 0:
                more = QLabel(f"+{leftover}")
                more.setStyleSheet("color: #6B7773; background: transparent; border: none;")
                col.addWidget(more)
            col.addStretch(1)
            grid.addWidget(frame, 1 + cell // 7, cell % 7)
        self._layout.replaceWidget(old, self._body)
        old.deleteLater()


class RunCalendar(QFrame):
    event_clicked = Signal(str, str)
    group_open_requested = Signal(object)
    range_changed = Signal()
    schedule_run_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = "week"
        self._anchor = date.today()
        self._events: list[CalendarEvent] = []
        self._agents: list[BoardAgent] = []
        self._agent_filter = ""
        self._status_filter = ""
        self._source_filter = ""
        self._popup: _GroupPopup | None = None
        self.setObjectName("RunCalendar")
        self.setStyleSheet(
            """
            QFrame#RunCalendar {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )

        title = QLabel("Календарь запусков")
        title.setFont(app_font(16, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent; border: none;")
        title.setWordWrap(True)
        self._period = QLabel()
        self._period.setFont(app_font(13))
        self._period.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        self._period.setWordWrap(True)

        prev_btn = QPushButton("<")
        next_btn = QPushButton(">")
        today_btn = QPushButton("Сегодня")
        for button in (prev_btn, next_btn, today_btn):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(32)
            button.setStyleSheet(_BTN)
        prev_btn.setFixedWidth(36)
        next_btn.setFixedWidth(36)
        prev_btn.clicked.connect(lambda: self._shift(-1))
        next_btn.clicked.connect(lambda: self._shift(1))
        today_btn.clicked.connect(self._go_today)

        self._day_btn = self._view_btn("День", "day")
        self._week_btn = self._view_btn("Неделя", "week")
        self._month_btn = self._view_btn("Месяц", "month")
        self._week_btn.setChecked(True)

        filters = QPushButton("Фильтры")
        filters.setCursor(Qt.CursorShape.PointingHandCursor)
        filters.setFixedHeight(32)
        filters.setStyleSheet(_BTN)
        filters.clicked.connect(self._toggle_filters)
        schedule = QPushButton("Запланировать запуск")
        schedule.setCursor(Qt.CursorShape.PointingHandCursor)
        schedule.setFixedHeight(32)
        schedule.setStyleSheet(_PRIMARY)
        schedule.clicked.connect(self._on_schedule)
        for button in (
            today_btn,
            self._day_btn,
            self._week_btn,
            self._month_btn,
            filters,
            schedule,
        ):
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(title)
        heading.addWidget(self._period)
        controls = QWidget()
        controls.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        flow = _FlowLayout(controls, spacing=8)
        for widget in (
            prev_btn,
            today_btn,
            next_btn,
            self._day_btn,
            self._week_btn,
            self._month_btn,
            filters,
            schedule,
        ):
            flow.addWidget(widget)

        head = QVBoxLayout()
        head.setSpacing(10)
        head.addLayout(heading)
        head.addWidget(controls)

        legend = QHBoxLayout()
        legend.setSpacing(12)
        for key in ("ok", "scheduled", "error", "paused"):
            _bg, border, label = _STATUS_STYLE[key]
            dot = QLabel("●  " + label)
            dot.setFont(app_font(11))
            dot.setStyleSheet(f"color: {border}; background: transparent; border: none;")
            legend.addWidget(dot)
        legend.addStretch(1)

        self._tags = QHBoxLayout()
        self._tags.setSpacing(6)
        self._tags_host = QWidget()
        self._tags_host.setLayout(self._tags)
        self._tags_host.setStyleSheet("background: transparent; border: none;")

        self._filters = QFrame()
        self._filters.setVisible(False)
        self._filters.setStyleSheet(
            "QFrame { background: #F7FBFA; border: 1px solid rgba(16,24,23,0.08); border-radius: 12px; }"
        )
        filt = QHBoxLayout(self._filters)
        filt.setContentsMargins(10, 8, 10, 8)
        self._agent_combo = QComboBox()
        self._status_combo = QComboBox()
        self._source_combo = QComboBox()
        self._agent_combo.addItem("Все агенты", "")
        self._status_combo.addItem("Все статусы", "")
        for key, meta in _STATUS_STYLE.items():
            self._status_combo.addItem(meta[2], key)
        self._source_combo.addItem("Все типы", "")
        self._source_combo.addItem("По расписанию", "schedule")
        self._source_combo.addItem("Вручную", "manual")
        self._source_combo.addItem("По событию", "event")
        for combo in (self._agent_combo, self._status_combo, self._source_combo):
            combo.setFixedHeight(32)
            combo.currentIndexChanged.connect(self._apply_filters)
        reset = QPushButton("Сбросить")
        reset.setCursor(Qt.CursorShape.PointingHandCursor)
        reset.setStyleSheet(_BTN)
        reset.setFixedHeight(32)
        reset.clicked.connect(self.clear_filters)
        filt.addWidget(QLabel("Агент"))
        filt.addWidget(self._agent_combo, 1)
        filt.addWidget(QLabel("Статус"))
        filt.addWidget(self._status_combo)
        filt.addWidget(QLabel("Тип"))
        filt.addWidget(self._source_combo)
        filt.addWidget(reset)

        self._week = _WeekGrid()
        self._week.event_clicked.connect(self._emit_event)
        self._week.group_clicked.connect(self._show_group_popup)
        self._month = _MonthGrid()
        self._month.event_clicked.connect(self._emit_event)
        self._month.group_clicked.connect(self._show_group_popup)
        self._month.setVisible(False)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(False)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(self._week)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addLayout(legend)
        layout.addWidget(self._tags_host)
        layout.addWidget(self._filters)
        layout.addWidget(self._scroll, 1)
        layout.addWidget(self._month, 1)
        self._refresh_period()

    def calendar_window(self) -> tuple[str, str]:
        start, end = window_for(self._view, self._anchor)
        return start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()

    def set_agents(self, agents: list[BoardAgent]) -> None:
        self._agents = [item for item in agents if item.kind == "workflow"]
        current = self._agent_filter
        self._agent_combo.blockSignals(True)
        self._agent_combo.clear()
        self._agent_combo.addItem("Все агенты", "")
        for agent in self._agents:
            self._agent_combo.addItem(agent.title or "ИИ-агент", agent.id)
        index = max(0, self._agent_combo.findData(current))
        self._agent_combo.setCurrentIndex(index)
        self._agent_combo.blockSignals(False)

    def set_events(self, events: list[CalendarEvent]) -> None:
        self._events = events
        self._render()

    def set_agent_filter(self, workflow_id: str) -> None:
        self._agent_filter = workflow_id or ""
        index = max(0, self._agent_combo.findData(self._agent_filter))
        self._agent_combo.blockSignals(True)
        self._agent_combo.setCurrentIndex(index)
        self._agent_combo.blockSignals(False)
        self._render_tags()
        self._render()

    def clear_filters(self) -> None:
        self._agent_filter = ""
        self._status_filter = ""
        self._source_filter = ""
        self._agent_combo.setCurrentIndex(0)
        self._status_combo.setCurrentIndex(0)
        self._source_combo.setCurrentIndex(0)
        self._render_tags()
        self._render()

    def _view_btn(self, text: str, key: str) -> QPushButton:
        button = QPushButton(text)
        button.setCheckable(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(32)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setStyleSheet(_BTN)
        button.clicked.connect(lambda _=False, view=key: self._set_view(view))
        return button

    def _set_view(self, view: str) -> None:
        self._view = view
        self._day_btn.setChecked(view == "day")
        self._week_btn.setChecked(view == "week")
        self._month_btn.setChecked(view == "month")
        self._refresh_period()
        self.range_changed.emit()
        self._render()

    def _shift(self, step: int) -> None:
        if self._view == "day":
            self._anchor += timedelta(days=step)
        elif self._view == "month":
            month = self._anchor.month + step
            year = self._anchor.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            self._anchor = date(year, month, 1)
        else:
            self._anchor += timedelta(days=7 * step)
        self._refresh_period()
        self.range_changed.emit()

    def _go_today(self) -> None:
        self._anchor = date.today()
        self._refresh_period()
        self.range_changed.emit()

    def _refresh_period(self) -> None:
        self._period.setText(format_period(self._view, self._anchor))

    def _toggle_filters(self) -> None:
        self._filters.setVisible(not self._filters.isVisible())

    def _apply_filters(self) -> None:
        self._agent_filter = str(self._agent_combo.currentData() or "")
        self._status_filter = str(self._status_combo.currentData() or "")
        self._source_filter = str(self._source_combo.currentData() or "")
        self._render_tags()
        self._render()

    def _visible_events(self) -> list[CalendarEvent]:
        items = list(self._events)
        if self._agent_filter:
            items = [item for item in items if item.workflow_id == self._agent_filter]
        if self._status_filter:
            items = [item for item in items if item.status == self._status_filter]
        if self._source_filter:
            items = [item for item in items if item.source == self._source_filter]
        return items

    def _render_tags(self) -> None:
        while self._tags.count():
            item = self._tags.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        tags: list[tuple[str, str]] = []
        if self._agent_filter:
            title = next((agent.title for agent in self._agents if agent.id == self._agent_filter), "агент")
            tags.append((f"Агент: {title}", "agent"))
        if self._status_filter:
            tags.append((f"Статус: {_STATUS_STYLE.get(self._status_filter, ('', '', self._status_filter))[2]}", "status"))
        if self._source_filter:
            tags.append((f"Тип: {_SOURCE_LABEL.get(self._source_filter, self._source_filter)}", "source"))
        for text, key in tags:
            chip = QPushButton(text + "  ×")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setStyleSheet(
                "QPushButton { background: #EAF7F3; color: #06483D; border: none; border-radius: 10px; padding: 4px 10px; }"
            )
            chip.clicked.connect(lambda _=False, kind=key: self._clear_one(kind))
            self._tags.addWidget(chip)
        if tags:
            reset = QPushButton("Сбросить")
            reset.setCursor(Qt.CursorShape.PointingHandCursor)
            reset.setStyleSheet(_BTN)
            reset.clicked.connect(self.clear_filters)
            self._tags.addWidget(reset)
        self._tags.addStretch(1)

    def _clear_one(self, kind: str) -> None:
        if kind == "agent":
            self._agent_combo.setCurrentIndex(0)
        elif kind == "status":
            self._status_combo.setCurrentIndex(0)
        else:
            self._source_combo.setCurrentIndex(0)

    def _render(self) -> None:
        events = self._visible_events()
        if self._view == "month":
            self._scroll.setVisible(False)
            self._month.setVisible(True)
            self._month.set_data(self._anchor, events)
            return
        self._month.setVisible(False)
        self._scroll.setVisible(True)
        if self._view == "day":
            days = [self._anchor]
        else:
            start = monday_of(self._anchor)
            days = [start + timedelta(days=offset) for offset in range(7)]
        self._week.set_data(days, events)
        QTimer.singleShot(0, self._scroll_to_now)

    def _scroll_to_now(self) -> None:
        if self._view == "month" or not self._scroll.isVisible():
            return
        now = datetime.now().astimezone()
        y = max(0, self._week.time_y(now) - 90)
        x = max(0, self._week.today_x() - 24)
        self._scroll.verticalScrollBar().setValue(y)
        self._scroll.horizontalScrollBar().setValue(x)

    def _emit_event(self, event: object) -> None:
        if not isinstance(event, CalendarEvent):
            return
        self.event_clicked.emit(event.workflow_id, event.run_id or "")

    def _show_group_popup(self, events: object) -> None:
        items = [item for item in (events or []) if isinstance(item, CalendarEvent)]
        if len(items) < 2:
            if items:
                self._emit_event(items[0])
            return
        if self._popup is not None:
            self._popup.close()
        popup = _GroupPopup(items, self.window())
        popup.event_clicked.connect(self._emit_event)
        popup.open_all_requested.connect(self._open_group)
        origin = QCursor.pos()
        popup.adjustSize()
        popup.move(origin.x() - 24, origin.y() + 8)
        popup.show()
        self._popup = popup

    def _open_group(self, events: object) -> None:
        if self._popup is not None:
            self._popup.close()
            self._popup = None
        self.group_open_requested.emit(events)

    def _on_schedule(self) -> None:
        agents = self._agents
        if not agents:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Запланировать запуск")
        layout = QVBoxLayout(dialog)
        combo = QComboBox()
        for agent in agents:
            combo.addItem(agent.title or "ИИ-агент", agent.id)
        if self._agent_filter:
            index = combo.findData(self._agent_filter)
            if index >= 0:
                combo.setCurrentIndex(index)
        when = QDateTimeEdit()
        when.setCalendarPopup(True)
        when.setDateTime(QDateTime.currentDateTime())
        when.setDisplayFormat("dd.MM.yyyy HH:mm")
        layout.addWidget(QLabel("Агент"))
        layout.addWidget(combo)
        layout.addWidget(QLabel("Время запуска"))
        layout.addWidget(when)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        workflow_id = str(combo.currentData() or "")
        qdt = when.dateTime()
        stamp = datetime(
            qdt.date().year(),
            qdt.date().month(),
            qdt.date().day(),
            qdt.time().hour(),
            qdt.time().minute(),
            tzinfo=datetime.now().astimezone().tzinfo,
        )
        self.schedule_run_requested.emit(workflow_id, stamp.isoformat())


def _clip(text: str, limit: int) -> str:
    value = " ".join((text or "").split())
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"
