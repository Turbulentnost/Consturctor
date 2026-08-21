from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import Card, ClarificationQuestion, can_publish
from app.ui.styles import card_qss, ghost_button_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.cursor_feed import (
    CursorFeedItem,
    format_tool_event,
    merge_stream_text,
    should_show_status,
    tool_header_title,
)
from app.ui.widgets.status_chip import StatusChip


class DemoPage(QWidget):
    publish_requested = Signal()
    run_demo_requested = Signal()
    cancelled = Signal()
    clarify_answer = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card: Card | None = None
        self._feed_items: list[CursorFeedItem] = []
        self._live_assistant: CursorFeedItem | None = None
        self._live_thinking: CursorFeedItem | None = None
        self._last_agent_text = ""
        self._last_thinking_text = ""

        title = QLabel("Дизайн и демо")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._status = StatusChip("ожидание", variant="warning")

        self._advance = QLabel("")
        self._advance.setFont(app_font(13))
        self._advance.setStyleSheet(
            "color: #06483D; background: #F3FAF7; border: 1px solid rgba(8,116,95,0.18);"
            "border-radius: 10px; padding: 10px 14px;"
        )
        self._advance.setWordWrap(True)
        self._advance.hide()

        self._feed_host = QWidget()
        self._feed_host.setStyleSheet("background: transparent;")
        self._feed_layout = QVBoxLayout(self._feed_host)
        self._feed_layout.setContentsMargins(0, 0, 0, 0)
        self._feed_layout.setSpacing(0)
        self._feed_layout.addStretch(1)

        self._feed_scroll = QScrollArea()
        self._feed_scroll.setWidgetResizable(True)
        self._feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_scroll.setMinimumHeight(280)
        self._feed_scroll.setWidget(self._feed_host)
        self._feed_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        feed_frame = QFrame()
        feed_frame.setStyleSheet(card_qss("DemoFeed", radius=16))
        feed_lay = QVBoxLayout(feed_frame)
        feed_lay.setContentsMargins(12, 12, 12, 12)
        feed_lay.addWidget(self._feed_scroll)

        self._clarify_host = QHBoxLayout()
        self._clarify_host.setSpacing(8)
        clarify_wrap = QWidget()
        clarify_wrap.setLayout(self._clarify_host)

        back = QPushButton("← Назад")
        back.setStyleSheet(ghost_button_qss())
        back.clicked.connect(self.cancelled.emit)

        self._run_btn = QPushButton("Запустить демо")
        self._run_btn.setStyleSheet(secondary_button_qss(radius=12))
        self._run_btn.clicked.connect(self.run_demo_requested.emit)

        self._publish_btn = QPushButton("Сохранить агента")
        self._publish_btn.setStyleSheet(primary_button_qss(radius=12))
        self._publish_btn.clicked.connect(self.publish_requested.emit)
        self._publish_btn.setEnabled(False)
        self._action_buttons = (back, self._run_btn, self._publish_btn)

        actions = QHBoxLayout()
        actions.addWidget(back)
        actions.addStretch(1)
        actions.addWidget(self._run_btn)
        actions.addWidget(self._publish_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self._status, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self._advance)
        layout.addWidget(feed_frame, 1)
        layout.addWidget(clarify_wrap)
        layout.addLayout(actions)

    def set_card(self, card: Card) -> None:
        self._card = card
        self._advance.hide()
        self.clear_feed()
        draft = card.playbook_draft
        demo = card.demo
        self._append_feed("system", f"Playbook: {draft.status}, шагов: {len(draft.steps)}")
        if demo.transcript:
            for line in demo.transcript[-3:]:
                self._append_feed("agent", line)
        elif demo.result.get("text"):
            self._append_feed("agent", str(demo.result.get("text")))
        if demo.ok:
            self._status.setText("демо пройдено")
            self._status.set_variant("success")
        elif demo.error:
            self._status.setText("ошибка демо")
            self._status.set_variant("danger")
        else:
            self._status.setText("ожидание демо")
            self._status.set_variant("warning")
        self._publish_btn.setEnabled(can_publish(card))
        self._set_clarify([])

    def show_advance(self, text: str) -> None:
        if text.strip():
            self._advance.setText(text)
            self._advance.show()
        else:
            self._advance.hide()

    def set_busy(self, busy: bool) -> None:
        for index, btn in enumerate(self._action_buttons):
            if index == 0:
                btn.setEnabled(not busy)
            elif index == 1:
                btn.setEnabled(not busy)
                btn.setText("Запуск…" if busy else "Запустить демо")
            else:
                btn.setEnabled(not busy and self._card is not None and can_publish(self._card))
        if busy:
            self._status.setText("ИИ работает…")
            self._status.set_variant("mint")
        elif self._card is not None:
            demo = self._card.demo
            if demo.ok:
                self._status.setText("демо пройдено")
                self._status.set_variant("success")
            elif demo.error:
                self._status.setText("ошибка демо")
                self._status.set_variant("danger")
            else:
                self._status.setText("ожидание демо")
                self._status.set_variant("warning")

    def clear_feed(self) -> None:
        self._feed_items.clear()
        self._live_assistant = None
        self._live_thinking = None
        self._last_agent_text = ""
        self._last_thinking_text = ""
        while self._feed_layout.count() > 1:
            item = self._feed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def handle_pipeline_event(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        et = event.get("type")
        if et == "agent_message":
            chunk = str(event.get("text") or "")
            if not chunk.strip():
                return
            merged = merge_stream_text(self._last_agent_text, chunk)
            if merged == self._last_agent_text:
                return
            self._last_agent_text = merged
            if self._live_assistant is not None:
                self._live_assistant.set_body_text(merged)
            else:
                self._append_feed("agent", merged, live=True)
            self._scroll_bottom()
        elif et == "thinking":
            chunk = str(event.get("text") or "").strip()
            if not chunk:
                return
            merged = merge_stream_text(self._last_thinking_text, chunk)
            if merged == self._last_thinking_text:
                return
            self._last_thinking_text = merged
            if self._live_thinking is not None:
                self._live_thinking.set_body_text(merged)
            else:
                self._append_feed("thinking", merged, live=True, title="Размышление")
            self._scroll_bottom()
        elif et == "tool":
            self._live_assistant = None
            self._live_thinking = None
            name = str(event.get("name") or "")
            status = str(event.get("status") or "")
            result = event.get("result")
            body = format_tool_event(name, status, result)
            self._append_feed("tool", body, title=tool_header_title(name, status))
        elif et in {"phase_start", "substep", "status"}:
            text = str(event.get("text") or "").strip()
            if text and (et != "status" or should_show_status(text)):
                self._append_feed("system", text)
                self._status.setText(text[:48] + ("…" if len(text) > 48 else ""))
                self._status.set_variant("mint")

    def _append_feed(
        self,
        kind: str,
        text: str,
        title: str = "",
        *,
        live: bool = False,
    ) -> None:
        cleaned = (text or "").strip()
        if not cleaned and kind not in {"tool"}:
            return
        item = CursorFeedItem(kind=kind, text=text, title=title)
        self._feed_items.append(item)
        count = self._feed_layout.count()
        self._feed_layout.insertWidget(max(0, count - 1), item)
        if live and kind == "agent":
            self._live_assistant = item
        elif live and kind == "thinking":
            self._live_thinking = item

    def _scroll_bottom(self) -> None:
        QTimer.singleShot(50, lambda: self._feed_scroll.verticalScrollBar().setValue(
            self._feed_scroll.verticalScrollBar().maximum()
        ))

    def _set_clarify(self, questions: list[ClarificationQuestion]) -> None:
        while self._clarify_host.count():
            item = self._clarify_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for q in questions[:4]:
            for opt in (q.options or [q.question]):
                btn = QPushButton(opt[:60])
                btn.setStyleSheet(secondary_button_qss(radius=10))
                btn.clicked.connect(lambda _=False, text=opt: self.clarify_answer.emit(text))
                self._clarify_host.addWidget(btn)

    def show_clarify(self, questions: list[ClarificationQuestion]) -> None:
        self._set_clarify(questions)
