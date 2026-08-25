"""Общая база файлов: быстрый переход, загрузка пулом, навигация по неделям."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, WorkflowFileItem, WorkflowListItem
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.file_type_icon import ElidedFilenameLabel, FileTypeIcon, file_type_style

_POOL_SIZE = 6
_TILE_W = 176
_MONTHS = (
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)

_TILE_QSS = """
QFrame#PlatformFileTile {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
QFrame#PlatformFileTile:hover {
    border: 1px solid rgba(8,116,95,0.35);
}
"""
_NAV_QSS = """
QPushButton {
    background: #FFFFFF;
    color: #06483D;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 12px;
}
QPushButton:hover { background: #F4F7F6; }
QPushButton:disabled { color: #9AA6A2; background: #F4F7F6; }
"""
_DOWNLOAD_QSS = """
QPushButton {
    background: #08745F;
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    padding: 6px 10px;
}
QPushButton:hover { background: #0A8670; }
"""
_SLIDER_QSS = """
QSlider::groove:horizontal {
    height: 6px;
    background: rgba(6,72,61,0.12);
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 18px;
    height: 18px;
    margin: -6px 0;
    background: #08745F;
    border-radius: 9px;
}
QSlider::sub-page:horizontal {
    background: #08745F;
    border-radius: 3px;
}
"""


@dataclass(frozen=True, slots=True)
class PlatformFileRow:
    workflow_id: str
    agent_title: str
    file_id: str
    filename: str
    source: str = "user"
    size: int = 0
    created_at: str = ""
    run_id: str = ""
    origin: str = ""
    scope: str = ""


@dataclass(frozen=True, slots=True)
class FileSessionGroup:
    workflow_id: str
    agent_title: str
    kind: str
    run_id: str
    title: str
    stamp: str
    sort_at: str
    ours: tuple[PlatformFileRow, ...]
    agent: tuple[PlatformFileRow, ...]


def parse_file_dt(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp


def week_monday(value: datetime | date) -> date:
    if isinstance(value, datetime):
        local = value.astimezone() if value.tzinfo else value
        day = local.date()
    else:
        day = value
    return day - timedelta(days=day.weekday())


def current_week_monday(today: date | None = None) -> date:
    return week_monday(today or date.today())


def week_range_text(monday: date) -> str:
    sunday = monday + timedelta(days=6)
    left = f"{monday.day} {_MONTHS[monday.month - 1]}"
    right = f"{sunday.day} {_MONTHS[sunday.month - 1]}"
    year = sunday.year
    return f"{left} - {right} {year}"


def week_title(monday: date, *, today: date | None = None) -> str:
    current = current_week_monday(today)
    if monday == current:
        return "Эта неделя"
    if monday == current - timedelta(days=7):
        return "Прошлая неделя"
    return week_range_text(monday)


def file_week_monday(created_at: str, *, fallback: date) -> date:
    parsed = parse_file_dt(created_at)
    if parsed is None:
        return fallback
    return week_monday(parsed)


def collect_weeks(items: list[PlatformFileRow], *, today: date | None = None) -> list[date]:
    current = current_week_monday(today)
    weeks = {current}
    for item in items:
        weeks.add(file_week_monday(item.created_at, fallback=current))
    return sorted(weeks)


def filter_week_files(
    items: list[PlatformFileRow],
    monday: date,
    query: str = "",
    *,
    today: date | None = None,
) -> list[PlatformFileRow]:
    current = current_week_monday(today)
    needle = (query or "").strip().casefold()
    rows: list[PlatformFileRow] = []
    for item in items:
        if file_week_monday(item.created_at, fallback=current) != monday:
            continue
        hay = f"{item.filename} {item.agent_title}".casefold()
        if needle and needle not in hay:
            continue
        rows.append(item)
    rows.sort(key=lambda item: (item.created_at or "", item.filename.casefold()), reverse=True)
    return rows


def rows_from_workflow_files(
    workflow: WorkflowListItem,
    files: object,
) -> list[PlatformFileRow]:
    user_files = list(getattr(files, "user_files", None) or [])
    agent_files = list(getattr(files, "agent_files", None) or [])
    title = workflow.title or "Агент"
    rows: list[PlatformFileRow] = []
    for item in user_files + agent_files:
        if not isinstance(item, WorkflowFileItem):
            continue
        if not item.id:
            continue
        rows.append(_row_from_item(item, workflow_id=workflow.id or item.workflow_id, agent_title=title))
    return rows


def _row_from_item(item: WorkflowFileItem, *, workflow_id: str, agent_title: str) -> PlatformFileRow:
    return PlatformFileRow(
        workflow_id=workflow_id,
        agent_title=agent_title,
        file_id=item.id,
        filename=item.filename or "file",
        source=item.source or "user",
        size=int(item.size or 0),
        created_at=item.created_at or "",
        run_id=(item.run_id or "").strip(),
        origin=item.origin or "",
        scope=item.scope or "",
    )


def session_kind(row: PlatformFileRow) -> str:
    if (row.run_id or "").strip() or row.source == "agent":
        return "run"
    return "formation"


def session_key(row: PlatformFileRow) -> tuple[str, str]:
    if session_kind(row) == "formation":
        return (row.workflow_id, "formation")
    return (row.workflow_id, f"run:{(row.run_id or '').strip() or 'unknown'}")


def session_stamp(rows: list[PlatformFileRow]) -> str:
    stamps = [parse_file_dt(item.created_at) for item in rows]
    latest = max((item for item in stamps if item is not None), default=None)
    if latest is None:
        return ""
    local = latest.astimezone() if latest.tzinfo else latest
    return f"{local.day} {_MONTHS[local.month - 1]}, {local.strftime('%H:%M')}"


def group_file_sessions(rows: list[PlatformFileRow]) -> list[FileSessionGroup]:
    buckets: dict[tuple[str, str], list[PlatformFileRow]] = {}
    order: list[tuple[str, str]] = []
    for row in rows:
        key = session_key(row)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(row)
    groups: list[FileSessionGroup] = []
    for key in order:
        items = buckets[key]
        first = items[0]
        kind = session_kind(first)
        run_id = (first.run_id or "").strip() if kind == "run" else ""
        stamp = session_stamp(items)
        sort_at = max((item.created_at or "" for item in items), default="")
        if kind == "formation":
            title = "Формирование агента"
        elif run_id:
            title = "Запуск агента"
        else:
            title = "Результаты агента"
        ours = tuple(item for item in items if item.source != "agent")
        agent = tuple(item for item in items if item.source == "agent")
        groups.append(
            FileSessionGroup(
                workflow_id=first.workflow_id,
                agent_title=first.agent_title or "Агент",
                kind=kind,
                run_id=run_id,
                title=title,
                stamp=stamp,
                sort_at=sort_at,
                ours=ours,
                agent=agent,
            )
        )
    groups.sort(
        key=lambda group: (
            group.agent_title.casefold(),
            0 if group.kind == "formation" else 1,
            -(_stamp_ts(group.sort_at)),
            group.run_id,
        )
    )
    return groups


def _stamp_ts(raw: str) -> float:
    parsed = parse_file_dt(raw)
    return parsed.timestamp() if parsed is not None else 0.0


def _format_size(size: int) -> str:
    value = max(0, int(size or 0))
    if value >= 1024 * 1024:
        return f"{value / (1024 * 1024):.1f} МБ"
    if value >= 1024:
        return f"{value / 1024:.1f} КБ"
    return f"{value} байт"


class PlatformFileTile(QFrame):
    download_requested = Signal(object)

    def __init__(self, row: PlatformFileRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = row
        self.setObjectName("PlatformFileTile")
        self.setStyleSheet(_TILE_QSS)
        self.setFixedWidth(_TILE_W)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Minimum)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        root.addWidget(FileTypeIcon(row.filename, self, size=48), 0, Qt.AlignmentFlag.AlignHCenter)
        name = ElidedFilenameLabel(row.filename, self)
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        name.setFont(app_font(12, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        agent = QLabel(row.agent_title or "Агент")
        agent.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        agent.setWordWrap(True)
        agent.setFont(app_font(11))
        agent.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        agent.setToolTip(row.agent_title or "Агент")
        style = file_type_style(row.filename)
        origin = "создан агентом" if row.source == "agent" else "загружен вами"
        meta = QLabel(f"{style.ext} · {_format_size(row.size)} · {origin}")
        meta.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        meta.setWordWrap(True)
        meta.setFont(app_font(10))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        download = QPushButton("Скачать")
        download.setCursor(Qt.CursorShape.PointingHandCursor)
        download.setFixedHeight(30)
        download.setFont(app_font(12, QFont.Weight.DemiBold))
        download.setStyleSheet(_DOWNLOAD_QSS)
        download.clicked.connect(lambda: self.download_requested.emit(self._row))
        root.addWidget(name)
        root.addWidget(agent)
        root.addWidget(meta)
        root.addStretch(1)
        root.addWidget(download)


class PlatformFilesPage(QWidget):
    _batch_ready = Signal(int, object)
    _progress = Signal(int, int, int)
    _failed = Signal(int, str)
    _finished = Signal(int)
    _download_done = Signal(str)
    _download_fail = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._items: list[PlatformFileRow] = []
        self._seen: set[tuple[str, str]] = set()
        self._weeks: list[date] = [current_week_monday()]
        self._week_index = 0
        self._loading = False
        self._generation = 0
        self._message = ""
        self._batch_ready.connect(self._on_batch)
        self._progress.connect(self._on_progress)
        self._failed.connect(self._on_failed)
        self._finished.connect(self._on_finished)
        self._download_done.connect(self._on_download_done)
        self._download_fail.connect(self._on_download_fail)

        title = QLabel("Файлы")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("Документы агентов за выбранную неделю: отдельно формирование и каждый запуск, наши файлы и файлы агента.")
        subtitle.setWordWrap(True)
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по файлам или агенту")
        self._search.setFixedHeight(38)
        self._search.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 1px solid rgba(16,24,23,0.10); "
            "border-radius: 12px; padding: 8px 12px; }"
        )
        self._search.textChanged.connect(lambda _text: self._render())
        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(38)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none; "
            "border-radius: 12px; padding: 8px 14px; }"
        )
        refresh.clicked.connect(lambda: self.refresh(force=True))
        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.addWidget(self._search, 1)
        tools.addWidget(refresh, 0)

        self._prev = QPushButton("<")
        self._next = QPushButton(">")
        for button in (self._prev, self._next):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(36, 36)
            button.setFont(app_font(16, QFont.Weight.DemiBold))
            button.setStyleSheet(_NAV_QSS)
        self._prev.clicked.connect(lambda: self._shift_week(-1))
        self._next.clicked.connect(lambda: self._shift_week(1))
        self._week_title = QLabel("Эта неделя")
        self._week_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._week_title.setFont(app_font(16, QFont.Weight.DemiBold))
        self._week_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._week_range = QLabel(week_range_text(current_week_monday()))
        self._week_range.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._week_range.setFont(app_font(12))
        self._week_range.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        week_text = QVBoxLayout()
        week_text.setContentsMargins(0, 0, 0, 0)
        week_text.setSpacing(2)
        week_text.addWidget(self._week_title)
        week_text.addWidget(self._week_range)
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(12)
        nav.addWidget(self._prev, 0, Qt.AlignmentFlag.AlignVCenter)
        nav.addLayout(week_text, 1)
        nav.addWidget(self._next, 0, Qt.AlignmentFlag.AlignVCenter)

        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.setValue(0)
        self._slider.setFixedHeight(28)
        self._slider.setStyleSheet(_SLIDER_QSS)
        self._slider.valueChanged.connect(self._on_slider)

        self._status = QLabel("Откройте неделю, файлы подгрузятся сразу после перехода.")
        self._status.setFont(app_font(12))
        self._status.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._bar = QProgressBar()
        self._bar.setRange(0, 0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setVisible(False)
        self._bar.setStyleSheet(
            "QProgressBar { background: rgba(6,72,61,0.12); border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background: #08745F; border-radius: 3px; }"
        )

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._body = QVBoxLayout(self._content)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(18)
        self._scroll.setWidget(self._content)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addLayout(tools)
        root.addLayout(nav)
        root.addWidget(self._slider)
        root.addWidget(self._status)
        root.addWidget(self._bar)
        root.addWidget(self._scroll, 1)
        self._render()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._render()

    def refresh(self, force: bool = False) -> None:
        if self._loading and not force:
            return
        if self._items and not force:
            self._render()
        self._generation += 1
        generation = self._generation
        self._loading = True
        self._message = ""
        if force:
            self._items = []
            self._seen.clear()
        self._bar.setRange(0, 0)
        self._bar.setVisible(True)
        self._status.setText("Загружаю файлы за эту неделю...")
        self._render()
        Thread(target=self._load, args=(generation,), daemon=True).start()

    def _load(self, generation: int) -> None:
        if self._load_catalog(generation):
            return
        try:
            workflows = self._api.list_workflows()
        except ApiError as exc:
            self._failed.emit(generation, exc.message)
            return
        alive = [item for item in workflows if item.id and item.phase != "deleted"]
        total = len(alive)
        self._progress.emit(generation, 0, total)
        if not alive:
            self._finished.emit(generation)
            return
        workers = max(1, min(_POOL_SIZE, total))
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            pending = {pool.submit(self._api.list_workflow_files, item.id): item for item in alive}
            for future in as_completed(pending):
                if generation != self._generation:
                    return
                workflow = pending[future]
                try:
                    files = future.result()
                except ApiError:
                    files = None
                batch = rows_from_workflow_files(workflow, files) if files is not None else []
                done += 1
                self._batch_ready.emit(generation, batch)
                self._progress.emit(generation, done, total)
        self._finished.emit(generation)

    def _load_catalog(self, generation: int) -> bool:
        try:
            items = self._api.list_platform_files()
        except ApiError:
            return False
        rows = [
            _row_from_item(item, workflow_id=item.workflow_id, agent_title=item.agent_title or "Агент")
            for item in items
            if item.id and item.workflow_id
        ]
        self._batch_ready.emit(generation, rows)
        self._finished.emit(generation)
        return True

    def _on_batch(self, generation: int, payload: object) -> None:
        if generation != self._generation:
            return
        rows = [item for item in payload if isinstance(item, PlatformFileRow)] if isinstance(payload, list) else []
        added = False
        for row in rows:
            key = (row.workflow_id, row.file_id)
            if key in self._seen:
                continue
            self._seen.add(key)
            self._items.append(row)
            added = True
        if added:
            self._sync_weeks(keep_week=self._selected_week())
            self._render()

    def _on_progress(self, generation: int, done: int, total: int) -> None:
        if generation != self._generation:
            return
        if total <= 0:
            self._bar.setRange(0, 0)
            self._status.setText("Загружаю список агентов...")
            return
        self._bar.setRange(0, total)
        self._bar.setValue(done)
        self._status.setText(f"Загружаю файлы пулом: {done} из {total} агентов")

    def _on_failed(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self._loading = False
        self._bar.setVisible(False)
        self._message = message or "Не удалось загрузить базу файлов."
        self._status.setText(self._message)
        self._render()

    def _on_finished(self, generation: int) -> None:
        if generation != self._generation:
            return
        self._loading = False
        self._bar.setVisible(False)
        self._sync_weeks(keep_week=self._selected_week())
        self._render()

    def _selected_week(self) -> date:
        if 0 <= self._week_index < len(self._weeks):
            return self._weeks[self._week_index]
        return current_week_monday()

    def _sync_weeks(self, *, keep_week: date) -> None:
        weeks = collect_weeks(self._items)
        self._weeks = weeks
        if keep_week in weeks:
            self._week_index = weeks.index(keep_week)
        else:
            current = current_week_monday()
            self._week_index = weeks.index(current) if current in weeks else len(weeks) - 1
        self._slider.blockSignals(True)
        self._slider.setMaximum(max(0, len(weeks) - 1))
        self._slider.setValue(self._week_index)
        self._slider.blockSignals(False)

    def _shift_week(self, delta: int) -> None:
        self._set_week(self._week_index + delta)

    def _on_slider(self, value: int) -> None:
        self._set_week(value)

    def _set_week(self, index: int) -> None:
        if not self._weeks:
            return
        next_index = max(0, min(len(self._weeks) - 1, int(index)))
        if next_index == self._week_index and self._slider.value() == next_index:
            return
        self._week_index = next_index
        self._slider.blockSignals(True)
        self._slider.setValue(next_index)
        self._slider.blockSignals(False)
        self._render()

    def _render(self) -> None:
        monday = self._selected_week()
        self._week_title.setText(week_title(monday))
        self._week_range.setText(week_range_text(monday))
        self._prev.setEnabled(self._week_index > 0)
        self._next.setEnabled(self._week_index < len(self._weeks) - 1)
        self._slider.setEnabled(len(self._weeks) > 1)
        rows = filter_week_files(self._items, monday, self._search.text())
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._message and not self._items:
            self._body.addWidget(self._empty(self._message))
            self._body.addStretch(1)
            return
        if not rows:
            if self._loading:
                text = "Страница уже открыта. Загружаю файлы этой недели."
            else:
                text = "На этой неделе файлов нет. Сдвиньте слайдер, чтобы посмотреть другие недели."
            self._body.addWidget(self._empty(text))
        else:
            for group in group_file_sessions(rows):
                self._body.addWidget(self._session_block(group))
        self._body.addStretch(1)
        if not self._loading:
            self._status.setText(f"{len(rows)} файлов за выбранную неделю")

    def _session_block(self, group: FileSessionGroup) -> QWidget:
        block = QFrame()
        block.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QVBoxLayout(block)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        when = f" · {group.stamp}" if group.stamp else ""
        head = QLabel(f"{group.title}{when}")
        head.setFont(app_font(16, QFont.Weight.DemiBold))
        head.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        agent = QLabel(group.agent_title)
        agent.setWordWrap(True)
        agent.setFont(app_font(12))
        agent.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        lay.addWidget(head)
        lay.addWidget(agent)
        if group.ours:
            lay.addWidget(self._source_label("Сформировано нами", len(group.ours)))
            lay.addWidget(self._tiles_grid(list(group.ours)))
        if group.agent:
            lay.addWidget(self._source_label("Создано агентом", len(group.agent)))
            lay.addWidget(self._tiles_grid(list(group.agent)))
        return block

    def _source_label(self, title: str, count: int) -> QWidget:
        label = QLabel(f"{title} · {count}")
        label.setFont(app_font(12, QFont.Weight.DemiBold))
        label.setStyleSheet("color: #08745F; background: transparent;")
        return label

    def _tiles_grid(self, rows: list[PlatformFileRow]) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        columns = max(1, self._scroll.viewport().width() // (_TILE_W + 12))
        for index, row in enumerate(rows):
            tile = PlatformFileTile(row)
            tile.download_requested.connect(self._save_file)
            grid.addWidget(tile, index // columns, index % columns, Qt.AlignmentFlag.AlignTop)
        return wrap

    def _empty(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(app_font(14))
        label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; padding: 40px;")
        return label

    def _save_file(self, raw: object) -> None:
        if not isinstance(raw, PlatformFileRow) or not raw.file_id or not raw.workflow_id:
            return
        dest, _ = QFileDialog.getSaveFileName(
            self,
            "Скачать файл",
            str(Path.home() / "Desktop" / (raw.filename or "file")),
            "Все файлы (*.*)",
        )
        if not dest:
            return
        self._status.setText(f"Скачиваю {raw.filename}...")

        def run() -> None:
            try:
                path = self._api.download_workflow_file_to(raw.workflow_id, raw.file_id, dest)
            except ApiError as exc:
                self._download_fail.emit(exc.message)
                return
            self._download_done.emit(str(path))

        Thread(target=run, daemon=True).start()

    def _on_download_done(self, path: str) -> None:
        self._status.setText(f"Файл сохранён: {Path(path).name}")

    def _on_download_fail(self, message: str) -> None:
        self._status.setText(message or "Не удалось скачать файл")
        QMessageBox.warning(self, "Файлы", message or "Не удалось скачать файл")
