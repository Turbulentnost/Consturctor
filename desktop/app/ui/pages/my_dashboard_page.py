from __future__ import annotations

from datetime import date, datetime
from threading import Thread

from PySide6.QtCore import QDate, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_TABLE_HEADERS = (
    "Задача",
    "Срок",
    "Статус выполнения",
    "Согласование",
    "Комментарий",
    "Дата выгрузки",
    "Исполнитель",
    "Источник",
)
_HEADER_RIGHT_GAP = 320
_PIE_CLOSED = QColor("#08745F")
_PIE_OPEN = QColor("#C5D9D3")

_CARD_QSS = """
QFrame#DashCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 16px;
}
"""
_ROW_QSS = """
QFrame#PersonRow {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 12px;
}
QFrame#PersonRow[expanded="true"] {
    border-color: rgba(8,116,95,0.35);
}
"""
_TABLE_QSS = """
QTableWidget {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.08);
    border-radius: 12px;
    gridline-color: rgba(16,24,23,0.10);
}
QHeaderView::section {
    background: #EEF7F3;
    color: #101817;
    border: none;
    border-right: 1px solid rgba(16,24,23,0.08);
    border-bottom: 1px solid rgba(16,24,23,0.10);
    padding: 8px 10px;
    font-weight: 600;
}
QTableWidget::item {
    padding: 8px 10px;
}
"""
_REFRESH_QSS = """
QPushButton {
    background: #08745F;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 0 16px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:pressed { background: #06483D; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""


def _tab_link_qss(*, active: bool) -> str:
    color = "#08745F" if active else "#6B7773"
    border = "#08745F" if active else "transparent"
    return f"""
    QPushButton {{
        background: transparent;
        border: none;
        border-bottom: 2px solid {border};
        color: {color};
        padding: 4px 0 6px 0;
        text-align: left;
    }}
    QPushButton:hover {{
        color: #06483D;
        border-bottom-color: #08745F;
    }}
    """


def _fmt_dt(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "—"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            if len(text) <= 10:
                return parsed.strftime("%d.%m.%Y")
            return parsed.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            continue
    return text


def _parse_dt(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _parse_date(raw: str) -> date | None:
    parsed = _parse_dt(raw)
    return parsed.date() if parsed else None


def _flatten_people(nodes: list) -> list[dict]:
    out: list[dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        out.append(node)
        out.extend(_flatten_people(list(node.get("subordinates") or [])))
    return out


def _person_stats(tasks: list[dict]) -> tuple[int, int, int]:
    total = len(tasks)
    closed = sum(1 for item in tasks if item.get("done"))
    late = sum(1 for item in tasks if _is_late(item))
    return total, closed, late


def _is_late(item: dict) -> bool:
    if item.get("late") is True:
        return True
    if not item.get("done"):
        return False
    completed = _parse_dt(str(item.get("completed_at") or ""))
    due = _parse_dt(str(item.get("due_at") or ""))
    return bool(completed and due and completed > due)


def _sorted_tasks(tasks: list[dict]) -> list[dict]:
    def key(item: dict) -> str:
        return str(item.get("created_at") or item.get("due_at") or "")

    return sorted(tasks, key=key, reverse=True)


class _KpiCard(QFrame):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DashCard")
        self.setStyleSheet(_CARD_QSS)
        self._value = QLabel("—")
        self._value.setFont(app_font(28, QFont.Weight.DemiBold))
        self._value.setStyleSheet("color: #101817; background: transparent;")
        caption = QLabel(title)
        caption.setFont(app_font(13, QFont.Weight.Medium))
        caption.setStyleSheet("color: #6B7773; background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(4)
        layout.addWidget(self._value)
        layout.addWidget(caption)

    def set_value(self, text: str) -> None:
        self._value.setText(text)


class _PieChart(QWidget):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._closed = 0
        self._open = 0
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Показать таблицу задач")

    def set_counts(self, *, closed: int, opened: int) -> None:
        self._closed = max(0, closed)
        self._open = max(0, opened)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(8, 8, -8, -8)
        total = self._closed + self._open
        if total <= 0:
            p.setPen(QPen(QColor("#D5E3DE"), 10))
            p.drawEllipse(rect.adjusted(10, 10, -10, -10))
            p.setPen(QColor("#6B7773"))
            p.setFont(app_font(12, QFont.Weight.Medium))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "нет задач")
            p.end()
            return
        closed_span = 360.0 * self._closed / total
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_PIE_CLOSED)
        p.drawPie(rect, int(90 * 16), int(-closed_span * 16))
        p.setBrush(_PIE_OPEN)
        p.drawPie(rect, int((90 - closed_span) * 16), int(-(360.0 - closed_span) * 16))
        hole = rect.adjusted(28, 28, -28, -28)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(hole)
        p.setPen(MAIN_TEXT)
        p.setFont(app_font(16, QFont.Weight.DemiBold))
        p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), str(total))
        p.end()


class _PersonCard(QFrame):
    toggled = Signal(str)
    table_requested = Signal(str)

    def __init__(self, person: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.fio = str(person.get("fio") or "—").strip() or "—"
        self._person = person
        self._expanded = False
        self.setObjectName("PersonRow")
        self.setStyleSheet(_ROW_QSS + _CARD_QSS)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        name = QLabel(self.fio)
        name.setFont(app_font(16, QFont.Weight.DemiBold))
        name.setStyleSheet("color: #101817; background: transparent;")
        position = str(person.get("position") or "").strip() or "—"
        role = QLabel(position)
        role.setFont(app_font(13))
        role.setStyleSheet("color: #6B7773; background: transparent;")
        head = QVBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(2)
        head.addWidget(name)
        head.addWidget(role)

        self._pie = _PieChart()
        self._pie.clicked.connect(lambda: self.table_requested.emit(self.fio))
        tasks = [item for item in (person.get("tasks") or []) if isinstance(item, dict)]
        total, closed, late = _person_stats(tasks)
        self._pie.set_counts(closed=closed, opened=max(0, total - closed))
        self._caption = QLabel(
            f"Всего {total} · закрыто {closed} · не вовремя закрыто {late}"
        )
        self._caption.setFont(app_font(13))
        self._caption.setStyleSheet("color: #3D4A46; background: transparent;")
        self._caption.setWordWrap(True)

        dash = QHBoxLayout()
        dash.setContentsMargins(0, 0, 0, 0)
        dash.setSpacing(18)
        dash.addWidget(self._pie, 0, Qt.AlignmentFlag.AlignTop)
        legend = QVBoxLayout()
        legend.setSpacing(6)
        legend.addWidget(self._caption)
        closed_l = QLabel("● закрытые")
        closed_l.setStyleSheet("color: #08745F; background: transparent;")
        open_l = QLabel("● ещё открытые")
        open_l.setStyleSheet("color: #6B7773; background: transparent;")
        legend.addWidget(closed_l)
        legend.addWidget(open_l)
        legend.addStretch(1)
        dash.addLayout(legend, 1)

        self._table = QTableWidget(0, len(_TABLE_HEADERS))
        self._table.setHorizontalHeaderLabels(list(_TABLE_HEADERS))
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(True)
        self._table.setShowGrid(True)
        self._table.setStyleSheet(_TABLE_QSS + scroll_bar_qss())
        header = self._table.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 5, 6, 7):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self._fill_table(_sorted_tasks(tasks))

        self._details = QWidget()
        details = QVBoxLayout(self._details)
        details.setContentsMargins(0, 8, 0, 0)
        details.setSpacing(10)
        details.addLayout(dash)
        details.addWidget(self._table)
        self._details.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(0)
        layout.addLayout(head)
        layout.addWidget(self._details)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = expanded
        self._details.setVisible(expanded)
        self.setProperty("expanded", "true" if expanded else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def reveal_table(self) -> None:
        if not self._expanded:
            self.set_expanded(True)
        self._table.setFocus(Qt.FocusReason.OtherFocusReason)
        self._table.scrollToTop()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            if self._details.isVisible() and self._details.geometry().contains(event.pos()):
                super().mouseReleaseEvent(event)
                return
            self.toggled.emit(self.fio)
        super().mouseReleaseEvent(event)

    def _fill_table(self, tasks: list[dict]) -> None:
        self._table.setRowCount(len(tasks))
        for row, item in enumerate(tasks):
            values = (
                str(item.get("title") or item.get("number") or "—"),
                _fmt_dt(str(item.get("due_at") or "")),
                str(item.get("status") or "—"),
                str(item.get("approval") or "—"),
                str(item.get("comment") or "—") or "—",
                _fmt_dt(str(item.get("exported_at") or "")),
                str(item.get("performer") or self.fio),
                str(item.get("source") or "erp_pm"),
            )
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value if value.strip() else "—")
                cell.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(row, col, cell)
            self._table.resizeRowToContents(row)
        if not tasks:
            self._table.setRowCount(1)
            empty = QTableWidgetItem("Задач не найдено")
            empty.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(0, 0, empty)
            self._table.setSpan(0, 0, 1, len(_TABLE_HEADERS))
        rows = max(self._table.rowCount(), 1)
        header_h = self._table.horizontalHeader().height()
        self._table.setMinimumHeight(min(360, header_h + 36 * rows + 8))


class MyDashboardPage(QWidget):
    _loaded = Signal(object)
    _failed = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._busy = False
        self._people: list[dict] = []
        self._cards: list[_PersonCard] = []
        self._erp_since: date | None = None
        self._dates_ready = False
        self._loaded.connect(self._show_data)
        self._failed.connect(self._show_error)

        title = QLabel("Мой дашборд")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")
        title.setContentsMargins(0, 0, _HEADER_RIGHT_GAP, 0)

        self._kpi_link = self._nav_link("KPI")
        self._people_link = self._nav_link("Мои сотрудники")
        self._kpi_link.clicked.connect(lambda: self._set_view("kpi"))
        self._people_link.clicked.connect(lambda: self._set_view("people"))
        tabs = QHBoxLayout()
        tabs.setContentsMargins(8, 0, _HEADER_RIGHT_GAP, 0)
        tabs.setSpacing(18)
        tabs.addWidget(self._kpi_link)
        tabs.addWidget(self._people_link)
        tabs.addStretch(1)

        self._status = QLabel("Загрузка задач из erp_pm и документооборота…")
        self._status.setFont(app_font(14))
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._kpi_open = _KpiCard("Открытые задачи")
        self._kpi_overdue = _KpiCard("Просроченные")
        self._kpi_done = _KpiCard("Выполненные")
        self._kpi_people = _KpiCard("Сотрудники")
        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        for card in (self._kpi_open, self._kpi_overdue, self._kpi_done, self._kpi_people):
            card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            kpi_row.addWidget(card)
        kpi_page = QWidget()
        kpi_box = QVBoxLayout(kpi_page)
        kpi_box.setContentsMargins(0, 0, 0, 0)
        kpi_box.setSpacing(12)
        kpi_box.addLayout(kpi_row)
        kpi_box.addStretch(1)

        period_label = QLabel("Период")
        period_label.setFont(app_font(13, QFont.Weight.Medium))
        period_label.setStyleSheet("color: #6B7773; background: transparent;")
        self._date_from = QDateEdit()
        self._date_to = QDateEdit()
        for editor in (self._date_from, self._date_to):
            editor.setCalendarPopup(True)
            editor.setDisplayFormat("dd.MM.yyyy")
            editor.setDate(QDate.currentDate())
        self._date_from.dateChanged.connect(self._on_period_changed)
        self._date_to.dateChanged.connect(self._on_period_changed)
        self._refresh = QPushButton("Обновить")
        self._refresh.setFixedHeight(36)
        self._refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh.setStyleSheet(_REFRESH_QSS)
        self._refresh.clicked.connect(self.refresh)
        period = QHBoxLayout()
        period.setContentsMargins(0, 0, 0, 0)
        period.setSpacing(10)
        period.addWidget(period_label)
        period.addWidget(QLabel("с"))
        period.addWidget(self._date_from)
        period.addWidget(QLabel("по"))
        period.addWidget(self._date_to)
        period.addWidget(self._refresh)
        period.addStretch(1)

        self._people_list = QVBoxLayout()
        self._people_list.setSpacing(8)
        people_inner = QWidget()
        people_inner.setStyleSheet("background: transparent;")
        people_inner.setLayout(self._people_list)
        people_page = QWidget()
        people_box = QVBoxLayout(people_page)
        people_box.setContentsMargins(0, 0, 0, 0)
        people_box.setSpacing(12)
        people_box.addLayout(period)
        people_box.addWidget(people_inner)

        self._stack = QStackedWidget()
        self._stack.addWidget(kpi_page)
        self._stack.addWidget(people_page)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        body = QVBoxLayout(inner)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(12)
        body.addWidget(title)
        body.addLayout(tabs)
        body.addWidget(self._status)
        body.addWidget(self._stack, 1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        self._scroll = scroll

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self._set_view("kpi")

    def _nav_link(self, text: str) -> QPushButton:
        button = QPushButton(text)
        button.setFlat(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFont(app_font(14, QFont.Weight.DemiBold))
        button.setStyleSheet(_tab_link_qss(active=False))
        return button

    def _set_view(self, view: str) -> None:
        self._stack.setCurrentIndex(0 if view == "kpi" else 1)
        self._kpi_link.setStyleSheet(_tab_link_qss(active=view == "kpi"))
        self._people_link.setStyleSheet(_tab_link_qss(active=view == "people"))

    def _on_period_changed(self, _date: QDate) -> None:
        if self._dates_ready and not self._busy:
            self.refresh()

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._refresh.setEnabled(False)
        self._status.setText("Загрузка задач из erp_pm и документооборота…")
        date_from = self._date_from.date().toString("yyyy-MM-dd") if self._dates_ready else ""
        date_to = self._date_to.date().toString("yyyy-MM-dd") if self._dates_ready else ""
        args: dict = {"include_done": True, "limit_per_person": 200, "include_self": True}
        if date_from and date_to:
            args["date_from"] = date_from
            args["date_to"] = date_to
        else:
            args["full_range"] = True

        def run() -> None:
            try:
                team = self._api.invoke_server_tool("onec.erp_subordinate_tasks", args)
            except ApiError as exc:
                self._failed.emit(exc.message)
                return
            self._loaded.emit(team)

        Thread(target=run, daemon=True).start()

    def _show_error(self, message: str) -> None:
        self._busy = False
        self._refresh.setEnabled(True)
        self._status.setText(message or "Не удалось загрузить дашборд")

    def _show_data(self, payload: object) -> None:
        self._busy = False
        self._refresh.setEnabled(True)
        team = payload if isinstance(payload, dict) else {}
        people = _flatten_people(list(team.get("tree") or []))
        self._people = people
        since = _parse_date(str(team.get("erp_since") or ""))
        if since is not None:
            self._erp_since = since
        if not self._dates_ready:
            self._apply_default_dates(team)
        self._update_kpi(people)
        self._render_people(people)
        source = str(team.get("source") or "erp_pm")
        task_count = sum(len(item.get("tasks") or []) for item in people)
        warning = str(team.get("docflow_warning") or "").strip()
        status = f"{task_count} задач · {len(people)} сотрудников · источник {source}"
        if warning:
            status = f"{status}\n{warning}"
        self._status.setText(status)
        self._status.setStyleSheet(
            f"color: {'#B45309' if warning else COLOR_CONTENT_MUTED.name()}; "
            "background: transparent;"
        )

    def _apply_default_dates(self, team: dict) -> None:
        start = _parse_date(str(team.get("erp_since") or team.get("date_from") or ""))
        finish = _parse_date(str(team.get("date_to") or "")) or date.today()
        if start is None:
            start = date.today()
        self._dates_ready = True
        self._date_from.blockSignals(True)
        self._date_to.blockSignals(True)
        self._date_from.setMinimumDate(QDate(start.year, start.month, start.day))
        self._date_from.setDate(QDate(start.year, start.month, start.day))
        self._date_to.setDate(QDate(finish.year, finish.month, finish.day))
        self._date_from.blockSignals(False)
        self._date_to.blockSignals(False)

    def _update_kpi(self, people: list[dict]) -> None:
        tasks: list[dict] = []
        for person in people:
            tasks.extend(item for item in (person.get("tasks") or []) if isinstance(item, dict))
        now = datetime.now()
        open_n = sum(1 for item in tasks if not item.get("done"))
        done_n = sum(1 for item in tasks if item.get("done"))
        overdue_n = 0
        for item in tasks:
            if item.get("done"):
                continue
            due = _parse_dt(str(item.get("due_at") or ""))
            if due is not None and due < now:
                overdue_n += 1
        self._kpi_open.set_value(str(open_n))
        self._kpi_overdue.set_value(str(overdue_n))
        self._kpi_done.set_value(str(done_n))
        self._kpi_people.set_value(str(len(people)))

    def _render_people(self, people: list[dict]) -> None:
        while self._people_list.count():
            item = self._people_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []
        if not people:
            empty = QLabel("Подчинённых в erp_pm нет.")
            empty.setWordWrap(True)
            empty.setFont(app_font(15))
            empty.setStyleSheet("color: #6B7773; background: transparent;")
            self._people_list.addWidget(empty)
            self._people_list.addStretch(1)
            return
        for person in people:
            card = _PersonCard(person)
            card.toggled.connect(self._toggle_person)
            card.table_requested.connect(self._reveal_person_table)
            self._people_list.addWidget(card)
            self._cards.append(card)
        self._people_list.addStretch(1)

    def _toggle_person(self, fio: str) -> None:
        for card in self._cards:
            if card.fio == fio:
                card.set_expanded(not card.is_expanded())
            else:
                card.set_expanded(False)

    def _reveal_person_table(self, fio: str) -> None:
        for card in self._cards:
            if card.fio == fio:
                card.reveal_table()
                self._scroll.ensureWidgetVisible(card._table)
            else:
                card.set_expanded(False)
