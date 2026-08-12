from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget

from app.api_client import RegulationCreationSession
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


class RegulationCreationPage(QWidget):
    message_requested = Signal(str, str)
    finished_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: RegulationCreationSession | None = None
        self._think_expanded = False
        self._thinking_text = ""
        self._messages_layout = QVBoxLayout()
        self._messages_layout.setContentsMargins(14, 14, 14, 14)
        self._messages_layout.setSpacing(10)
        content = QWidget()
        content.setLayout(self._messages_layout)
        content.setStyleSheet("background: transparent;")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        self._input = QTextEdit()
        self._input.setFixedHeight(72)
        self._input.setPlaceholderText("Напишите ответ...")
        self._send = QPushButton("➤")
        self._send.setFixedSize(46, 46)
        self._send.clicked.connect(self._submit)
        input_row = QHBoxLayout()
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send)
        title = QLabel("Создание регламента")
        title.setFont(app_font(26, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("Ответьте на вопросы, и ИИ подготовит регламент в стиле ваших документов")
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(scroll, 1)
        layout.addLayout(input_row)

    def set_session(self, session: RegulationCreationSession) -> None:
        self._session = session
        if session.status != "generating":
            self._thinking_text = ""
        self._render_messages()
        generating = session.status == "generating"
        finalized = session.status == "finalized"
        self._input.setEnabled(not generating and not finalized)
        self._send.setEnabled(not generating and not finalized)
        if finalized and session.result_regulation is not None:
            self.finished_requested.emit(session.result_regulation)

    def _render_messages(self) -> None:
        while self._messages_layout.count():
            item = self._messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._session is None:
            return
        for message in self._session.messages:
            self._messages_layout.addWidget(self._bubble(message.content, user=message.role == "user"))
        if self._session.status == "generating" and self._thinking_text:
            self._messages_layout.addWidget(self._think_block())
        self._messages_layout.addStretch(1)

    def _submit(self) -> None:
        if self._session is None:
            return
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self.message_requested.emit(self._session.draft_id, text)

    def append_stream_event(self, event_type: str, text: str) -> None:
        if event_type == "thinking" and text:
            self._thinking_text += text
            self._think_expanded = True
            self._render_messages()

    def _bubble(self, text: str, *, user: bool) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if user:
            row.addStretch(1)
        bubble = QFrame()
        bubble.setMaximumWidth(720)
        bubble.setStyleSheet(
            """
            QFrame {
                background: %s;
                border: 1px solid rgba(8,116,95,0.14);
                border-radius: 16px;
            }
            """
            % ("rgba(8,116,95,0.09)" if user else "#FFFFFF")
        )
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(14, 10, 14, 10)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(app_font(13))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(label)
        row.addWidget(bubble)
        if not user:
            row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _think_block(self) -> QWidget:
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
        layout.setSpacing(8)
        toggle = QPushButton(("think ▾" if self._think_expanded else "think ▸") + " Cursor Agent формирует следующий вопрос")
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setFont(app_font(12, QFont.Weight.DemiBold))
        toggle.setStyleSheet(
            """
            QPushButton {
                text-align: left;
                border: none;
                background: transparent;
                color: #08745F;
                padding: 0;
            }
            """
        )
        toggle.clicked.connect(self._toggle_think)
        layout.addWidget(toggle)
        if self._think_expanded:
            text = QLabel(
                self._thinking_text
            )
            text.setWordWrap(True)
            text.setFont(app_font(12))
            text.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            layout.addWidget(text)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(card)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _toggle_think(self) -> None:
        self._think_expanded = not self._think_expanded
        self._render_messages()
