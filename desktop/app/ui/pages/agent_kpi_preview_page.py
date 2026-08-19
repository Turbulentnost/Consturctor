from __future__ import annotations

import re
from threading import Thread

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.api_client import (
    AgentKpi,
    ApiClient,
    ApiError,
    WorkflowRecord,
    _parse_agent_kpi,
)
from app.ui.pages.kpi_page import PlanFactTile, format_agent_kpi_summary
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_USER_MENU_RESERVE = 320


_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_SECONDARY = """
QPushButton {
    background: #FFFFFF; color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 12px; padding: 0 16px;
}
QPushButton:hover { background: #F4F7F6; }
"""
_TOOL_CARD = """
QFrame#KpiToolCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 12px;
}
"""


class AgentKpiPreviewPage(QWidget):
    back_requested = Signal()
    confirm_requested = Signal(object)
    _stream_event = Signal(str, str)
    _done = Signal(object)
    _fail = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._record: WorkflowRecord | None = None
        self._kpi: AgentKpi | None = None
        self._busy = False
        self._busy_n = 0
        self._busy_phrase = "Куратор собирает KPI"
        self._live_tools: list[dict[str, str]] = []
        self._busy_frames = ("◐", "◓", "◑", "◒")
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(280)
        self._busy_timer.timeout.connect(self._tick_activity)

        title = QLabel("KPI агента")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("План — как агент должен работать. Факт — что произошло после запусков.")
        subtitle.setWordWrap(True)
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._back = QPushButton("Назад")
        self._back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back.setFixedHeight(36)
        self._back.setStyleSheet(_SECONDARY)
        self._back.clicked.connect(self.back_requested.emit)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setFont(app_font(12, QFont.Weight.Medium))
        self._banner.setStyleSheet("color: #08745F; background: #EAF7F3; border-radius: 10px; padding: 8px 10px;")
        self._banner.hide()

        self._thinking = QTextEdit()
        self._thinking.setReadOnly(True)
        self._thinking.setFont(app_font(12))
        self._thinking.setFixedHeight(140)
        self._thinking.setStyleSheet(
            "QTextEdit { background: #FFFFFF; color: #101817; border: 1px solid rgba(16,24,23,0.10);"
            " border-radius: 12px; padding: 8px; }"
        )
        self._thinking.hide()

        self._tools = QVBoxLayout()
        self._tools.setContentsMargins(0, 0, 0, 0)
        self._tools.setSpacing(8)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setFont(app_font(14))
        self._summary.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._summary.hide()

        self._tiles = QGridLayout()
        self._tiles.setContentsMargins(0, 0, 0, 0)
        self._tiles.setHorizontalSpacing(12)
        self._tiles.setVerticalSpacing(12)

        self._save = QPushButton("Сохранить")
        self._save.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save.setFixedHeight(40)
        self._save.setFont(app_font(13, QFont.Weight.DemiBold))
        self._save.setStyleSheet(_PRIMARY)
        self._save.clicked.connect(self._on_save)
        self._save.setEnabled(False)

        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner_lay = QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(12)
        inner_lay.addWidget(self._banner)
        inner_lay.addWidget(self._thinking)
        inner_lay.addLayout(self._tools)
        inner_lay.addWidget(self._summary)
        inner_lay.addLayout(self._tiles)
        inner_lay.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        scroll.setWidget(inner)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, _USER_MENU_RESERVE, 0)
        header.setSpacing(12)
        header.addWidget(title, 1)
        header.addWidget(self._back, 0, Qt.AlignmentFlag.AlignRight)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 8)
        root.setSpacing(12)
        root.addLayout(header)
        root.addWidget(subtitle)
        root.addWidget(scroll, 1)
        root.addWidget(self._save, 0, Qt.AlignmentFlag.AlignRight)

        self._stream_event.connect(self._on_stream_event)
        self._done.connect(self._on_done)
        self._fail.connect(self._on_fail)

    def current_record(self) -> WorkflowRecord | None:
        return self._record

    def start(self, record: WorkflowRecord) -> None:
        self._record = record
        self._kpi = None
        self._live_tools = []
        self._thinking.clear()
        self._thinking.show()
        self._summary.hide()
        self._save.setEnabled(False)
        self._clear_layout(self._tools)
        self._clear_layout(self._tiles)
        self._set_busy(True, "Куратор собирает KPI")

        def work() -> None:
            try:
                updated = self._api.stream_generate_workflow_kpi(record.id, self._emit_event)
                self._done.emit(updated)
            except ApiError as exc:
                self._fail.emit(exc.message)
            except Exception as exc:  # noqa: BLE001
                self._fail.emit(str(exc))

        Thread(target=work, daemon=True).start()

    def set_busy(self, busy: bool) -> None:
        self._save.setEnabled((not busy) and self._kpi is not None and bool(self._kpi.tiles))
        self._save.setText("Сохраняю…" if busy else "Сохранить")
        self._back.setEnabled(not busy)

    def _emit_event(self, event_type: str, text: str) -> None:
        self._stream_event.emit(event_type, text)

    def _on_stream_event(self, event_type: str, text: str) -> None:
        incoming = (text or "").strip()
        if incoming:
            self._busy_phrase = incoming.splitlines()[-1][:120]
        if event_type == "error" and incoming:
            self._thinking.append(incoming)
            return
        if event_type in {"decision", "system", "message"} and incoming:
            if self._parse_tool_activity(incoming):
                self._render_tools()
                return
            self._thinking.append(incoming)
            return
        if event_type in {"thinking", "assistant"} and text:
            current = self._thinking.toPlainText()
            self._thinking.setPlainText((current + text)[-4000:])
            cursor = self._thinking.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self._thinking.setTextCursor(cursor)

    def _on_done(self, record: object) -> None:
        if isinstance(record, WorkflowRecord):
            self._record = record
            raw = (record.local_run or {}).get("kpi")
            if isinstance(raw, dict):
                self._kpi = _parse_agent_kpi(raw)
        self._set_busy(False)
        self._thinking.hide()
        self._render_result()

    def _on_fail(self, message: str) -> None:
        self._set_busy(False)
        self._thinking.append(message)
        self._banner.setText(message or "Не удалось собрать KPI")
        self._banner.setStyleSheet("color: #9B1C1C; background: #FFF4F4; border-radius: 10px; padding: 8px 10px;")
        self._banner.show()
        if self._record is not None:
            raw = (self._record.local_run or {}).get("kpi")
            if isinstance(raw, dict):
                self._kpi = _parse_agent_kpi(raw)
                self._render_result()

    def _on_save(self) -> None:
        if self._record is None or self._kpi is None:
            return
        self.confirm_requested.emit(self._record)

    def _set_busy(self, busy: bool, phrase: str = "") -> None:
        self._busy = busy
        if phrase:
            self._busy_phrase = phrase
        self._save.setEnabled((not busy) and self._kpi is not None and bool(self._kpi.tiles))
        self._save.setText("Сохранить")
        self._back.setEnabled(not busy)
        if busy:
            self._banner.setStyleSheet(
                "color: #08745F; background: #EAF7F3; border-radius: 10px; padding: 8px 10px;"
            )
            self._banner.show()
            self._busy_timer.start()
            self._tick_activity()
        else:
            self._busy_timer.stop()
            self._banner.hide()

    def _tick_activity(self) -> None:
        if not self._busy:
            return
        self._busy_n = (self._busy_n % 4) + 1
        frame = self._busy_frames[(self._busy_n - 1) % len(self._busy_frames)]
        running = next((item for item in self._live_tools if item.get("status") == "running"), None)
        if running:
            phrase = f"Вызываю {running.get('name') or 'инструмент'}…"
        else:
            phrase = self._busy_phrase or "Куратор собирает KPI"
        if len(phrase) > 100:
            phrase = phrase[:97] + "…"
        self._banner.setText(f"{frame} Система работает — {phrase}")

    def _parse_tool_activity(self, text: str) -> bool:
        raw = (text or "").strip()
        if not raw:
            return False
        low = raw.casefold()
        call = re.search(
            r"(?:Cursor вызывает|Выполняю на этом компьютере|Выполняю на компьютере)\s*[:«\"]?\s*«?([^\n»]+)»?",
            raw,
            re.IGNORECASE,
        )
        if call and ("вызывает" in low or "выполняю" in low):
            self._upsert_tool(call.group(1).strip(" «»\"'.,;"), "running", "Выполняется…")
            return True
        progress = re.search(r"«([^»]+)»\s*:\s*(читаю|загружаю|ожидаю)\b(.+)$", raw, re.IGNORECASE)
        if progress:
            self._upsert_tool(progress.group(1).strip(), "running", (progress.group(2) + progress.group(3)).strip())
            return True
        done = re.search(r"«([^»]+)»\s*:\s*готово\.?", raw, re.IGNORECASE)
        if done:
            self._upsert_tool(done.group(1).strip(), "ok", "Готово")
            return True
        return False

    def _upsert_tool(self, name: str, status: str, detail: str) -> None:
        for item in self._live_tools:
            if item.get("name") == name:
                item["status"] = status
                item["detail"] = detail
                return
        self._live_tools.append({"name": name, "status": status, "detail": detail})

    def _render_tools(self) -> None:
        self._clear_layout(self._tools)
        for item in self._live_tools:
            card = QFrame()
            card.setObjectName("KpiToolCard")
            card.setStyleSheet(_TOOL_CARD)
            title = QLabel(f"Инструмент: {item.get('name') or 'tool'}")
            title.setFont(app_font(13, QFont.Weight.DemiBold))
            title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            body = QLabel(item.get("detail") or "")
            body.setWordWrap(True)
            body.setFont(app_font(12))
            body.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            lay = QVBoxLayout(card)
            lay.setContentsMargins(12, 10, 12, 10)
            lay.setSpacing(4)
            lay.addWidget(title)
            lay.addWidget(body)
            self._tools.addWidget(card)

    def _render_result(self) -> None:
        self._clear_layout(self._tiles)
        kpi = self._kpi
        if kpi is None or not kpi.tiles:
            self._summary.setText("Не удалось собрать KPI. Назад — к паспорту, либо сохраните базовый набор позже.")
            self._summary.show()
            return
        self._summary.setText(format_agent_kpi_summary(kpi))
        self._summary.show()
        for index, tile in enumerate(kpi.tiles):
            self._tiles.addWidget(PlanFactTile(tile), index // 2, index % 2)
        self._save.setEnabled(not self._busy)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
