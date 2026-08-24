from __future__ import annotations

from datetime import datetime
from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentRunHistoryItem, ApiClient, ApiError
from app.tools.result_files import extract_result_files
from app.ui.pages.agent_run_page import _event_card, _friendly_event
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


_SECONDARY = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #F4F7F6; }
"""
_CARD = """
QFrame#HistoryCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 16px;
}
"""
_ROW = """
QFrame#HistoryRow {
    background: #F7FAF9;
    border: 1px solid #EAF1EE;
    border-radius: 12px;
}
QFrame#HistoryRow:hover {
    background: #EEF5F2;
    border-color: #C9D9D3;
}
"""
_DETAIL_CARD = """
QFrame#HistoryDetailCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 18px;
}
"""


class AgentHistoryPage(QWidget):
    back_requested = Signal()
    failed = Signal(str)
    _run_ready = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._workflow_id = ""
        self._agent_title = "ИИ-агент"
        self._runs: list[AgentRunHistoryItem] = []
        self._busy = False
        self._run_ready.connect(self._show_run_detail)
        self.failed.connect(self._on_failed)
        self._build()

    def _build(self) -> None:
        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_list_page())
        self._stack.addWidget(self._build_detail_page())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._stack, 1)

    def _build_list_page(self) -> QWidget:
        page = QWidget()
        self._title = QLabel("ИИ-агент")
        self._title.setFont(app_font(28, QFont.Weight.DemiBold))
        self._title.setWordWrap(True)
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("История запусков")
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        back = QPushButton("Назад")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(36)
        back.setStyleSheet(_SECONDARY)
        back.clicked.connect(self.back_requested.emit)
        back_row = QHBoxLayout()
        back_row.addStretch(1)
        back_row.addWidget(back)

        self._empty = QLabel("Запусков ещё не было")
        self._empty.setFont(app_font(13))
        self._empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._list = QVBoxLayout()
        self._list.setContentsMargins(16, 14, 16, 14)
        self._list.setSpacing(10)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner.setLayout(self._list)
        card = QFrame()
        card.setObjectName("HistoryCard")
        card.setStyleSheet(_CARD)
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.addWidget(inner)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._title)
        layout.addWidget(subtitle)
        layout.addLayout(back_row)
        layout.addWidget(self._empty)
        layout.addWidget(scroll, 1)
        return page

    def _build_detail_page(self) -> QWidget:
        page = QWidget()
        self._detail_title = QLabel("ИИ-агент")
        self._detail_title.setFont(app_font(22, QFont.Weight.DemiBold))
        self._detail_title.setWordWrap(True)
        self._detail_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._detail_subtitle = QLabel("Ход выполнения")
        self._detail_subtitle.setFont(app_font(13))
        self._detail_subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        back = QPushButton("Назад")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(36)
        back.setStyleSheet(_SECONDARY)
        back.clicked.connect(self._show_list)
        back_row = QHBoxLayout()
        back_row.addStretch(1)
        back_row.addWidget(back)

        self._feed_layout = QVBoxLayout()
        self._feed_layout.setContentsMargins(14, 14, 14, 14)
        self._feed_layout.setSpacing(10)
        feed_inner = QWidget()
        feed_inner.setStyleSheet("background: transparent;")
        feed_inner.setLayout(self._feed_layout)
        feed_scroll = QScrollArea()
        feed_scroll.setWidgetResizable(True)
        feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        feed_scroll.setWidget(feed_inner)
        feed_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        feed_card = QFrame()
        feed_card.setObjectName("HistoryDetailCard")
        feed_card.setStyleSheet(_DETAIL_CARD)
        feed_card_lay = QVBoxLayout(feed_card)
        feed_card_lay.setContentsMargins(0, 0, 0, 0)
        feed_card_lay.addWidget(feed_scroll)

        side = QFrame()
        side.setObjectName("HistoryDetailCard")
        side.setStyleSheet(_DETAIL_CARD)
        side.setFixedWidth(260)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(16, 16, 16, 16)
        side_lay.setSpacing(10)
        side_heading = QLabel("Запуск")
        side_heading.setFont(app_font(13, QFont.Weight.DemiBold))
        side_heading.setStyleSheet("color: #06483D; background: transparent;")
        self._detail_meta = QLabel("")
        self._detail_meta.setWordWrap(True)
        self._detail_meta.setFont(app_font(12))
        self._detail_meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._detail_status = QLabel("")
        self._detail_status.setWordWrap(True)
        self._detail_status.setFont(app_font(12))
        self._detail_status.setStyleSheet("color: #08745F; background: transparent;")
        side_lay.addWidget(side_heading)
        side_lay.addWidget(self._detail_meta)
        side_lay.addWidget(self._detail_status)
        side_lay.addStretch(1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(feed_card, 1)
        body.addWidget(side, 0)

        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._detail_title)
        layout.addWidget(self._detail_subtitle)
        layout.addLayout(back_row)
        layout.addLayout(body, 1)
        return page

    def show_history(self, *, title: str, workflow_id: str, runs: list[AgentRunHistoryItem]) -> None:
        self._agent_title = (title or "").strip() or "ИИ-агент"
        self._workflow_id = workflow_id
        self._runs = list(runs or [])
        self._title.setText(self._agent_title)
        self._render_list()
        self._show_list()

    def open_run(
        self,
        *,
        title: str,
        workflow_id: str,
        run_id: str = "",
        runs: list[AgentRunHistoryItem] | None = None,
        detail: AgentRunHistoryItem | None = None,
    ) -> None:
        self._agent_title = (title or "").strip() or "ИИ-агент"
        self._workflow_id = workflow_id
        if runs is not None:
            self._runs = list(runs)
            self._render_list()
        self._title.setText(self._agent_title)
        if detail is not None:
            self._show_run_detail(detail)
            return
        wanted = (run_id or "").strip()
        item = next((row for row in self._runs if row.id == wanted), None) if wanted else None
        if item is None and self._runs:
            item = self._runs[0]
        if item is None and wanted:
            item = AgentRunHistoryItem(id=wanted, workflow_id=workflow_id)
        if item is None:
            self._show_list()
            return
        self._open_run(item)

    def _show_list(self) -> None:
        self._stack.setCurrentIndex(0)

    def _render_list(self) -> None:
        while self._list.count():
            taken = self._list.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.deleteLater()
        self._empty.setVisible(not self._runs)
        for item in self._runs:
            self._list.addWidget(_HistoryRow(item, self._open_run))
        self._list.addStretch(1)

    def _open_run(self, item: AgentRunHistoryItem) -> None:
        if self._busy:
            return
        self._busy = True
        workflow_id = item.workflow_id or self._workflow_id

        def run() -> None:
            try:
                detail = self._api.get_agent_run(workflow_id, item.id)
            except ApiError:
                detail = item
            self._run_ready.emit(detail)

        Thread(target=run, daemon=True).start()

    def _show_run_detail(self, payload: object) -> None:
        self._busy = False
        if not isinstance(payload, AgentRunHistoryItem):
            return
        self._detail_title.setText(self._agent_title)
        when = _format_iso(payload.started_at) or "—"
        source = _source_label(payload)
        status = _status_label(payload.status)
        self._detail_subtitle.setText(f"{when}  ·  {source}  ·  {status}")
        finished = _format_iso(payload.finished_at)
        reason = (payload.trigger_reason or "").strip()
        self._detail_meta.setText(
            f"Источник: {source}"
            + (f"\nПричина: {reason}" if reason else "")
            + f"\nНачало: {when}"
            + (f"\nКонец: {finished}" if finished else "")
        )
        self._detail_status.setText(status.capitalize() if status != "готово" else "Готово")
        if payload.status == "error":
            color = "#9B1C1C"
        elif payload.status in {"started", "running"}:
            color = "#2F6FED"
        else:
            color = "#08745F"
        self._detail_status.setStyleSheet(f"color: {color}; background: transparent;")
        self._render_feed(_events_for_run(payload))
        self._stack.setCurrentIndex(1)

    def _render_feed(self, events: list[dict]) -> None:
        while self._feed_layout.count():
            taken = self._feed_layout.takeAt(0)
            widget = taken.widget()
            if widget is not None:
                widget.deleteLater()
        for index, event in enumerate(events, start=1):
            item = dict(event)
            item.setdefault("event_key", f"h{index}")
            kind = str(item.get("type") or "")
            expanded = kind in {"tool", "tool_result", "work_result", "result"}
            self._feed_layout.addWidget(_event_card(item, expanded=expanded))
        if not events:
            empty = QLabel("Ход выполнения этого запуска не сохранился.")
            empty.setWordWrap(True)
            empty.setFont(app_font(13))
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._feed_layout.addWidget(empty)
        self._feed_layout.addStretch(1)

    def _on_failed(self, _message: str) -> None:
        self._busy = False


class _HistoryRow(QFrame):
    def __init__(self, item: AgentRunHistoryItem, on_open) -> None:
        super().__init__()
        self._item = item
        self._on_open = on_open
        self.setObjectName("HistoryRow")
        self.setStyleSheet(_ROW)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        when = _format_iso(item.started_at) or "—"
        source = _source_label(item)
        status = _status_label(item.status)
        meta = QLabel(f"{when}  ·  {source}  ·  {status}")
        meta.setFont(app_font(11, QFont.Weight.DemiBold))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        reason_text = (item.trigger_reason or "").strip()
        reason = QLabel(reason_text)
        reason.setFont(app_font(12, QFont.Weight.Medium))
        reason.setWordWrap(True)
        reason.setStyleSheet("color: #08745F; background: transparent;")
        reason.setVisible(bool(reason_text))
        task = QLabel(item.message.strip() or "Типовая задача агента")
        task.setFont(app_font(13, QFont.Weight.DemiBold))
        task.setWordWrap(True)
        task.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        answer = (item.answer or "").strip()
        if len(answer) > 280:
            answer = answer[:280].rstrip() + "…"
        body = QLabel(answer or "Нет текста результата")
        body.setFont(app_font(12))
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)
        layout.addWidget(meta)
        layout.addWidget(reason)
        layout.addWidget(task)
        layout.addWidget(body)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_open(self._item)
        super().mousePressEvent(event)


def _events_for_run(item: AgentRunHistoryItem) -> list[dict]:
    events: list[dict] = []
    for raw in item.events or []:
        if not isinstance(raw, dict):
            continue
        friendly = _friendly_event(raw)
        if friendly is None:
            continue
        if str(friendly.get("type") or "") == "status":
            continue
        events.append(friendly)
        kind = str(friendly.get("type") or "")
        payload = friendly.get("result") if kind in {"tool", "tool_result"} else raw
        for path in extract_result_files(payload, tool=str(friendly.get("tool") or "")):
            events.append({"type": "file", "path": str(path), "text": path.name})
    if events:
        return events
    if item.message.strip():
        events.append({"type": "user_message", "text": item.message.strip()})
    if item.status in {"started", "running"}:
        events.append(
            {
                "type": "system",
                "text": "Запуск ещё выполняется. Этот экран показывает историю, а не живой ход.",
            }
        )
    if item.status == "error":
        events.append({"type": "error", "message": item.answer.strip() or "Прогон завершился с ошибкой."})
    elif item.answer.strip():
        events.append({"type": "agent_message", "text": item.answer.strip()})
    return events


def _source_label(item: AgentRunHistoryItem) -> str:
    if item.source != "trigger":
        return "чат"
    kind = (item.trigger_kind or "").strip()
    if kind == "event":
        return "триггер · изменение"
    if kind in {"time", "interval"}:
        return "триггер · наступило время"
    return "триггер"


def _status_label(status: str) -> str:
    if status == "ok":
        return "готово"
    if status == "error":
        return "ошибка"
    if status in {"started", "running"}:
        return "выполняется"
    return status or "в работе"


def _format_iso(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:19].replace("T", " ")
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%d.%m.%Y %H:%M")
