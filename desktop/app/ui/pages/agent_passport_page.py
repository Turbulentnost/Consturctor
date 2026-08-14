"""Паспорт ИИ-агента: карточка слева, полноценный чат уточнений справа."""

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

from app.api_client import AgentPassport, AgentSuggestion, PassportSession
from app.ui.pages.readiness_page import ChatInput
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_FIELD_ROWS = (
    ("name", "ИИ-агент"),
    ("goal", "Цель"),
    ("trigger", "Триггер"),
    ("receives", "Получает"),
    ("checks", "Проверяет"),
    ("decisions", "Принимает решения"),
    ("can_autonomous", "Может самостоятельно"),
    ("needs_human_approval", "Требует подтверждения человека"),
    ("forbidden", "Не может"),
    ("result", "Результат"),
)
_FIELD_LABELS = {key: label for key, label in _FIELD_ROWS}


class AgentPassportPage(QWidget):
    back_requested = Signal()
    finished_requested = Signal(object)
    draft_requested = Signal(object)
    answer_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suggestion: AgentSuggestion | None = None
        self._session: PassportSession | None = None
        self._qa_history: list[tuple[str, str]] = []
        self._current_question: dict | None = None
        self._busy = False
        self._chat_stick_to_bottom = True

        self._title = QLabel("Паспорт ИИ-агента")
        self._title.setFont(app_font(28, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._title.setWordWrap(True)

        self._subtitle = QLabel("Агент уточнит пробелы в паспорте в чате справа.")
        self._subtitle.setFont(app_font(13))
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        back = QPushButton("Назад")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(36)
        back.setStyleSheet(_secondary_btn_qss())
        back.clicked.connect(self.back_requested.emit)

        header_text = QVBoxLayout()
        header_text.setSpacing(4)
        header_text.addWidget(self._title)
        header_text.addWidget(self._subtitle)

        header = QHBoxLayout()
        header.addLayout(header_text, 1)
        header.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)

        self._passport_card = self._build_passport_card()
        self._chat_card = self._build_chat_card()

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._passport_card, 3)
        columns.addWidget(self._chat_card, 2)

        self._status = QLabel("")
        self._status.setFont(app_font(12, QFont.Weight.Medium))
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color: #2D7A5E; background: transparent;")

        self._finish_btn = QPushButton("Далее · план")
        self._finish_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._finish_btn.setFixedHeight(40)
        self._finish_btn.setMinimumWidth(160)
        self._finish_btn.setFont(app_font(13, QFont.Weight.DemiBold))
        self._finish_btn.setStyleSheet(_primary_btn_qss())
        self._finish_btn.setEnabled(False)
        self._finish_btn.clicked.connect(self._on_finish)

        footer = QHBoxLayout()
        footer.addWidget(self._status, 1)
        footer.addWidget(self._finish_btn, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addLayout(header)
        root.addLayout(columns, 1)
        root.addLayout(footer)

    def start(self, suggestion: AgentSuggestion) -> None:
        self._suggestion = suggestion
        self._session = None
        self._qa_history = []
        self._current_question = None
        self._busy = True
        self._title.setText(suggestion.title or "Паспорт ИИ-агента")
        self._subtitle.setText(suggestion.description or "Собираю паспорт и уточняющие вопросы…")
        self._render_passport(AgentPassport())
        self._render_chat(loading=True, loading_text="Собираю черновик паспорта агента…")
        self._finish_btn.setEnabled(False)
        self._set_status("Агент готовит паспорт…")
        self.draft_requested.emit(suggestion)

    def apply_session(self, session: PassportSession) -> None:
        self._busy = False
        self._session = session
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._apply_passport(session.passport)

    def show_error(self, message: str) -> None:
        self._busy = False
        self._input.setEnabled(True)
        self._send_btn.setEnabled(True)
        self._set_status(message, error=True)
        self._render_chat(loading=False)

    def _apply_passport(self, passport: AgentPassport) -> None:
        self._render_passport(passport)
        missing = list(passport.missing_fields or [])
        questions = list(passport.questions or [])
        ready = bool(passport.name.strip()) and not missing
        if questions and not ready:
            self._current_question = questions[0]
            prompt = str(self._current_question.get("prompt") or "Уточните поле паспорта")
            self._render_chat(current_prompt=prompt)
            labels = [_FIELD_LABELS.get(item, item) for item in missing[:4]]
            self._set_status(
                "Нужны уточнения: " + ", ".join(labels) + ("…" if len(missing) > 4 else "")
            )
        else:
            self._current_question = None
            self._render_chat(current_prompt="")
            self._set_status("Паспорт готов — можно перейти к планированию workflow.")
        self._finish_btn.setEnabled(ready)

    def _build_passport_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("PassportCard")
        card.setStyleSheet(
            """
            QFrame#PassportCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 18px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        heading = QLabel("Паспорт агента")
        heading.setFont(app_font(15, QFont.Weight.DemiBold))
        heading.setStyleSheet("color: #06483D; background: transparent;")
        layout.addWidget(heading)

        hint = QLabel("Карточка обновляется после каждого ответа в чате.")
        hint.setFont(app_font(11))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(hint)

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self._fields_layout = QVBoxLayout(host)
        self._fields_layout.setContentsMargins(0, 0, 0, 0)
        self._fields_layout.setSpacing(8)
        self._field_value_labels: dict[str, QLabel] = {}
        self._field_row_frames: dict[str, QFrame] = {}
        for key, label in _FIELD_ROWS:
            row = QFrame()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(12, 8, 12, 8)
            row_layout.setSpacing(2)
            title = QLabel(label)
            title.setFont(app_font(10, QFont.Weight.DemiBold))
            title.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            value = QLabel("—")
            value.setFont(app_font(12))
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            row_layout.addWidget(title)
            row_layout.addWidget(value)
            self._fields_layout.addWidget(row)
            self._field_value_labels[key] = value
            self._field_row_frames[key] = row
        self._fields_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        layout.addWidget(scroll, 1)
        return card

    def _build_chat_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("PassportChatCard")
        card.setMinimumWidth(360)
        card.setMaximumWidth(520)
        card.setStyleSheet(
            """
            QFrame#PassportChatCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 18px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        heading = QLabel("Чат с агентом")
        heading.setFont(app_font(15, QFont.Weight.DemiBold))
        heading.setStyleSheet("color: #06483D; background: transparent;")
        layout.addWidget(heading)

        hint = QLabel("Отвечайте своими словами — агент дозаполнит паспорт.")
        hint.setFont(app_font(11))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(hint)

        self._messages_host = QWidget()
        self._messages_host.setStyleSheet("background: transparent;")
        self._messages_layout = QVBoxLayout(self._messages_host)
        self._messages_layout.setContentsMargins(0, 0, 0, 0)
        self._messages_layout.setSpacing(10)
        self._messages_layout.addStretch(1)

        self._messages_scroll = QScrollArea()
        self._messages_scroll.setWidgetResizable(True)
        self._messages_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._messages_scroll.setWidget(self._messages_host)
        self._messages_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        self._messages_scroll.verticalScrollBar().valueChanged.connect(self._sync_chat_scroll_state)
        layout.addWidget(self._messages_scroll, 1)

        input_row = QHBoxLayout()
        input_row.setSpacing(8)
        self._input = ChatInput()
        self._input.setPlaceholderText("Напишите ответ агенту…")
        self._input.send_requested.connect(self._on_send)
        self._send_btn = QPushButton("Отправить")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFixedHeight(44)
        self._send_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._send_btn.setStyleSheet(_primary_btn_qss())
        self._send_btn.clicked.connect(self._on_send)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(input_row)
        return card

    def _render_passport(self, passport: AgentPassport) -> None:
        missing = set(passport.missing_fields or [])
        for key, _label in _FIELD_ROWS:
            value = str(getattr(passport, key, "") or "").strip()
            label = self._field_value_labels[key]
            frame = self._field_row_frames[key]
            if value:
                label.setText(value)
                label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            else:
                label.setText("не заполнено")
                label.setStyleSheet("color: #B07A20; background: transparent;")
            if key in missing:
                frame.setStyleSheet(
                    "QFrame { background: #FFF8EF; border: 1px solid #F0DFC2; border-radius: 12px; }"
                )
            else:
                frame.setStyleSheet(
                    "QFrame { background: #F7FAF9; border: 1px solid #EAF1EE; border-radius: 12px; }"
                )

    def _render_chat(self, *, loading: bool = False, loading_text: str = "", current_prompt: str = "") -> None:
        while self._messages_layout.count():
            item = self._messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if loading:
            self._messages_layout.addWidget(self._assistant_bubble(loading_text or "Думаю…"))
            self._messages_layout.addStretch(1)
            self._input.setEnabled(False)
            self._send_btn.setEnabled(False)
            self._scroll_chat_to_bottom()
            return

        if not self._qa_history and not current_prompt:
            self._messages_layout.addWidget(
                self._assistant_bubble(
                    "Уточнений нет — паспорт заполнен. Можно нажать «Далее · план»."
                )
            )
        for prompt, answer in self._qa_history:
            self._messages_layout.addWidget(self._assistant_bubble(prompt))
            self._messages_layout.addWidget(self._user_bubble(answer))
        if current_prompt:
            self._messages_layout.addWidget(self._assistant_bubble(current_prompt))
        self._messages_layout.addStretch(1)
        self._input.setEnabled(not self._busy and bool(current_prompt))
        self._send_btn.setEnabled(not self._busy and bool(current_prompt))
        self._scroll_chat_to_bottom()

    def _assistant_bubble(self, text: str) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setMaximumWidth(360)
        bubble.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(14, 12, 14, 12)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(app_font(13))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(label)
        row.addWidget(bubble)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _user_bubble(self, text: str) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        bubble = QFrame()
        bubble.setMaximumWidth(320)
        bubble.setStyleSheet(
            """
            QFrame {
                background: rgba(8,116,95,0.09);
                border: 1px solid rgba(8,116,95,0.14);
                border-radius: 18px;
            }
            """
        )
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(14, 10, 14, 10)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(app_font(13))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(label)
        row.addWidget(bubble)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _on_send(self) -> None:
        if self._busy or self._session is None or not self._current_question:
            return
        answer = self._input.toPlainText().strip()
        if not answer:
            self._set_status("Введите ответ агенту.", error=True)
            return
        prompt = str(self._current_question.get("prompt") or "Уточните поле паспорта")
        field = str(self._current_question.get("field") or "")
        qid = str(self._current_question.get("id") or "")
        self._qa_history.append((prompt, answer))
        self._input.clear()
        self._busy = True
        self._render_chat(loading=True, loading_text="Проверяю ответ и обновляю паспорт…")
        self._set_status("Агент обрабатывает ответ…")
        answers: dict[str, str] = {}
        if qid:
            answers[qid] = answer
        if field:
            answers[field] = answer
        if not answers:
            answers["answer"] = answer
        self.answer_requested.emit(answers)

    def current_session(self) -> PassportSession | None:
        return self._session

    def _on_finish(self) -> None:
        if self._session is None:
            return
        if self._session.passport.missing_fields:
            self._set_status("Сначала ответьте на все уточнения в чате.", error=True)
            return
        self.finished_requested.emit(self._session)

    def _set_status(self, message: str, *, error: bool = False) -> None:
        color = "#B00020" if error else "#2D7A5E"
        self._status.setStyleSheet(f"color: {color}; background: transparent;")
        self._status.setText(message)

    def _sync_chat_scroll_state(self) -> None:
        bar = self._messages_scroll.verticalScrollBar()
        self._chat_stick_to_bottom = bar.value() >= max(0, bar.maximum() - 24)

    def _scroll_chat_to_bottom(self) -> None:
        def _go() -> None:
            if not self._chat_stick_to_bottom:
                return
            bar = self._messages_scroll.verticalScrollBar()
            bar.setValue(bar.maximum())

        QTimer.singleShot(0, _go)
        QTimer.singleShot(80, _go)


def _primary_btn_qss() -> str:
    return """
        QPushButton {
            background: #08745F;
            color: #FFFFFF;
            border: none;
            border-radius: 14px;
            padding: 0 18px;
        }
        QPushButton:hover { background: #0A8670; }
        QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
    """


def _secondary_btn_qss() -> str:
    return """
        QPushButton {
            background: #FFFFFF;
            color: #06483D;
            border: 1px solid rgba(16,24,23,0.12);
            border-radius: 14px;
            padding: 0 14px;
            font-weight: 600;
        }
        QPushButton:hover { background: #F4F7F6; }
    """
