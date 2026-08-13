from __future__ import annotations

from threading import Thread

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.api_client import ApiClient, ApiError, WorkflowRecord
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


_PRIMARY = """
QPushButton {
    background: #08745F; color: #FFFFFF; border: none;
    border-radius: 14px; padding: 0 18px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""

_CARD = """
QFrame#AgentRunCard {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 18px;
}
"""

_INPUT = """
QPlainTextEdit {
    background: #FFFFFF; color: #101817;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 12px;
    padding: 8px 12px;
    selection-background-color: #08745F;
}
"""


class AgentRunPage(QWidget):
    failed = Signal(str)
    _event_ready = Signal(object)
    _done = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._workflow: WorkflowRecord | None = None
        self._tools: list[dict] = []
        self._events: list[dict] = []
        self._event_ready.connect(self._append_event)
        self._done.connect(self._on_done)
        self.failed.connect(self._show_error)
        self._build()

    def _build(self) -> None:
        title = QLabel("Запуск ИИ-агента")
        title.setFont(app_font(22, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        body = QHBoxLayout()
        body.setSpacing(14)

        center_card = QFrame()
        center_card.setObjectName("AgentRunCard")
        center_card.setStyleSheet(_CARD)
        center = QVBoxLayout(center_card)
        center.setContentsMargins(16, 14, 16, 14)
        center.setSpacing(10)

        self._feed_layout = QVBoxLayout()
        self._feed_layout.setContentsMargins(14, 14, 14, 14)
        self._feed_layout.setSpacing(10)
        feed_inner = QWidget()
        feed_inner.setStyleSheet("background: transparent;")
        feed_inner.setLayout(self._feed_layout)
        self._feed_scroll = QScrollArea()
        self._feed_scroll.setWidgetResizable(True)
        self._feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_scroll.setWidget(feed_inner)
        self._feed_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        self._input = QPlainTextEdit()
        self._input.setFixedHeight(58)
        self._input.setPlaceholderText("Напишите задачу агенту...")
        self._input.setFont(app_font(12))
        self._input.setStyleSheet(_INPUT)
        self._send = QPushButton("➤")
        self._send.setFixedSize(42, 42)
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setStyleSheet(_PRIMARY)
        self._send.clicked.connect(self._submit)
        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send, 0, Qt.AlignmentFlag.AlignTop)

        center.addWidget(self._feed_scroll, 1)
        center.addLayout(input_row, 0)

        side_card = QFrame()
        side_card.setObjectName("AgentRunCard")
        side_card.setStyleSheet(_CARD)
        side_card.setFixedWidth(260)
        side = QVBoxLayout(side_card)
        side.setContentsMargins(16, 16, 16, 16)
        side.setSpacing(10)
        side.addWidget(_section("Этапы запуска"))
        for text in ("Задача", "Инструменты", "Выполнение", "Готово"):
            side.addWidget(_side_item(text))
        side.addWidget(_section("Инструменты local MCP"))
        self._tools_label = QLabel("Загружаем инструменты...")
        self._tools_label.setWordWrap(True)
        self._tools_label.setFont(app_font(12))
        self._tools_label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        side.addWidget(self._tools_label)
        side.addStretch(1)

        body.addWidget(center_card, 1)
        body.addWidget(side_card, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(title)
        root.addLayout(body, 1)

    def start(self, workflow: WorkflowRecord) -> None:
        self._workflow = workflow
        self._events = [
            {"type": "system", "text": f"Готов к запуску агента «{workflow.title or 'ИИ-агент'}»."}
        ]
        self._render()
        try:
            self._tools = self._api.list_agent_tools()
        except ApiError as exc:
            self._tools = []
            self.failed.emit(exc.message)
        names = [str(item.get("name") or "") for item in self._tools if item.get("name")]
        self._tools_label.setText(", ".join(names) if names else "Инструменты не найдены")

    def _submit(self) -> None:
        if self._workflow is None:
            return
        message = self._input.toPlainText().strip()
        if not message:
            return
        self._input.clear()
        self._send.setEnabled(False)
        self._append_event({"type": "user_message", "text": message})
        workflow_id = self._workflow.id

        def run() -> None:
            try:
                result = self._api.stream_workflow_agent_run(
                    workflow_id,
                    message,
                    lambda payload: self._event_ready.emit(payload),
                )
            except ApiError as exc:
                self.failed.emit(exc.message)
                return
            self._done.emit(result)

        Thread(target=run, daemon=True).start()

    def _append_event(self, event: object) -> None:
        if isinstance(event, dict):
            self._events.append(event)
            self._render()

    def _on_done(self, _result: object) -> None:
        self._send.setEnabled(True)
        self._append_event({"type": "system", "text": "Агент завершил выполнение задачи."})

    def _show_error(self, message: str) -> None:
        self._send.setEnabled(True)
        self._append_event({"type": "error", "message": message})

    def _render(self) -> None:
        while self._feed_layout.count():
            item = self._feed_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for event in self._events:
            self._feed_layout.addWidget(_event_card(event))
        self._feed_layout.addStretch(1)
        QTimer.singleShot(0, lambda: self._feed_scroll.verticalScrollBar().setValue(self._feed_scroll.verticalScrollBar().maximum()))


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(app_font(13, QFont.Weight.DemiBold))
    label.setStyleSheet("color: #06483D; background: transparent;")
    return label


def _side_item(text: str) -> QLabel:
    label = QLabel(f"○ {text}")
    label.setFont(app_font(12, QFont.Weight.Medium))
    label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    return label


def _event_card(event: dict) -> QWidget:
    event_type = str(event.get("type") or "system")
    text = str(event.get("text") or event.get("message") or "")
    if event_type == "tool_call":
        text = f"Вызов инструмента: {event.get('tool')}\n{event.get('arguments')}"
    elif event_type == "tool_result":
        text = f"Результат инструмента: {event.get('tool')}\n{event.get('result')}"
    heading = {
        "thinking": "Thinking",
        "tool_call": "Tool call",
        "tool_result": "Tool result",
        "agent_message": "Агент",
        "user_message": "Вы",
        "error": "Ошибка",
    }.get(event_type, "Система")
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    if event_type == "user_message":
        row.addStretch(1)
    card = QFrame()
    card.setMaximumWidth(720)
    card.setStyleSheet(
        """
        QFrame {
            background: #FFFFFF;
            border: 1px solid rgba(8,116,95,0.14);
            border-radius: 16px;
        }
        """
    )
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 14, 10)
    title = QLabel(heading)
    title.setFont(app_font(12, QFont.Weight.DemiBold))
    title.setStyleSheet("color: #08745F; background: transparent;")
    body = QLabel(text)
    body.setWordWrap(True)
    body.setFont(app_font(12))
    body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
    layout.addWidget(title)
    layout.addWidget(body)
    row.addWidget(card)
    if event_type != "user_message":
        row.addStretch(1)
    wrap = QWidget()
    wrap.setStyleSheet("background: transparent;")
    wrap.setLayout(row)
    return wrap
