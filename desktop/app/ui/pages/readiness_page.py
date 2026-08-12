from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentReadinessResult, QuestionChatMessage, QuestionChatSession, ReadinessChange, ReadinessQuestion
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


_CHAT_WIDTH = 600
_PANEL_WIDTH = 260


class ChatInput(QTextEdit):
    send_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(66)
        self.setPlaceholderText("Напишите ответ своими словами...")
        self.setStyleSheet(
            """
            QTextEdit {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 18px;
                padding: 12px 54px 12px 14px;
                color: #101817;
            }
            """
        )

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.send_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ReadinessPage(QWidget):
    back_requested = Signal()
    answer_requested = Signal(str, str)
    chat_requested = Signal(str)
    chat_message_requested = Signal(str, str)
    change_decision_requested = Signal(str, str, str)
    finalize_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result: AgentReadinessResult | None = None
        self._chat: QuestionChatSession | None = None
        self._input: ChatInput | None = None

        self._content = QVBoxLayout()
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(16)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        scroll_content.setLayout(self._content)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(scroll_content)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll, 1)

    def set_result(self, result: AgentReadinessResult) -> None:
        self._result = result
        self._render()

    def set_chat(self, chat: QuestionChatSession | None) -> None:
        self._chat = chat
        self._render()

    def _render(self) -> None:
        _clear_layout(self._content)
        self._input = None
        if self._result is None:
            return

        unanswered = [question for question in self._result.questions if not question.answered]
        current = unanswered[0] if unanswered else None
        answered_count = len(self._result.questions) - len(unanswered)

        self._content.addWidget(self._header())
        self._content.addWidget(self._progress_card(self._result.score, answered_count))

        body = QHBoxLayout()
        body.setSpacing(24)
        chat_column = QVBoxLayout()
        chat_column.setSpacing(12)
        chat_column.addWidget(self._chat_card(current))
        chat_column.addWidget(self._footer_actions())
        chat_column.addStretch(1)

        chat_wrap = QWidget()
        chat_wrap.setFixedWidth(_CHAT_WIDTH)
        chat_wrap.setStyleSheet("background: transparent;")
        chat_wrap.setLayout(chat_column)
        body.addWidget(chat_wrap, 0)

        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._progress_panel(self._result.questions, current))
        right_layout.addStretch(1)
        body.addWidget(right_wrap, 0)

        body_wrap = QWidget()
        body_wrap.setStyleSheet("background: transparent;")
        body_wrap.setLayout(body)
        self._content.addWidget(body_wrap, 1)
        self._content.addStretch(1)

    def _header(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        title = QLabel("Уточнение регламента")
        title.setFont(app_font(26, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("Я задам несколько вопросов, чтобы агент мог выполнять процесс без ошибок")
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(title)
        layout.addWidget(subtitle)
        return wrap

    def _progress_card(self, score: int, answered_count: int) -> QWidget:
        card = _soft_card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)
        row = QHBoxLayout()
        label = QLabel(f"Готовность регламента — {score}%")
        label.setFont(app_font(12, QFont.Weight.DemiBold))
        label.setStyleSheet("color: #06483D; background: transparent;")
        row.addWidget(label)
        row.addStretch(1)
        count = QLabel(f"Уточнено параметров: {answered_count}")
        count.setFont(app_font(12, QFont.Weight.DemiBold))
        count.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        row.addWidget(count)
        layout.addLayout(row)

        progress = QProgressBar()
        progress.setRange(0, 100)
        progress.setValue(score)
        progress.setTextVisible(False)
        progress.setFixedHeight(5)
        progress.setStyleSheet(_progress_qss())
        layout.addWidget(progress)
        return card

    def _chat_card(self, question: ReadinessQuestion | None) -> QWidget:
        card = _soft_card()
        card.setFixedWidth(_CHAT_WIDTH)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        top = QHBoxLayout()
        avatar = QLabel("AI")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setStyleSheet(
            """
            QLabel {
                background: #08745F;
                color: #FFFFFF;
                border-radius: 17px;
            }
            """
        )
        top.addWidget(avatar)
        title = QVBoxLayout()
        name = QLabel("ИИ-помощник")
        name.setFont(app_font(13, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        status = QLabel("Анализирует регламент")
        status.setFont(app_font(11))
        status.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        title.addWidget(name)
        title.addWidget(status)
        top.addLayout(title)
        top.addStretch(1)
        layout.addLayout(top)

        if question is None:
            layout.addWidget(self._assistant_bubble("Все вопросы уточнены. Можно перейти к согласованию изменений."))
            return card

        if not self._chat_matches(question):
            open_chat = QPushButton("Начать уточнение")
            open_chat.setCursor(Qt.CursorShape.PointingHandCursor)
            open_chat.clicked.connect(lambda _checked=False, qid=question.question_id: self.chat_requested.emit(qid))
            layout.addWidget(open_chat)
            return card

        layout.addWidget(self._message_area(question))

        if not question.answered:
            layout.addWidget(self._quick_answers(question))
            layout.addWidget(self._input_bar(question))
        return card

    def _message_area(self, question: ReadinessQuestion) -> QWidget:
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        messages_layout = QVBoxLayout(content)
        messages_layout.setContentsMargins(0, 0, 0, 0)
        messages_layout.setSpacing(12)
        messages = self._chat.messages if self._chat is not None else []
        for message in messages:
            messages_layout.addWidget(self._message_bubble(message, question))
        change = self._change_for_question(question)
        if change is not None and change.status == "pending":
            messages_layout.addWidget(self._change_proposal(change))
        messages_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(260)
        scroll.setWidget(content)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        return scroll

    def _first_assistant_bubble(self, question: ReadinessQuestion) -> QWidget:
        function_title = self._context_function_title(question)
        quote = self._first_context_quote()
        section = self._first_context_section()
        source = f" из раздела «{section}»" if section else ""
        text = (
            f"Я взял этот фрагмент{source} и увидел в нём функцию «{function_title}». "
            f"{_gap_explanation(question)}"
        )
        return self._assistant_bubble(text, quote=quote, question=question, section=section)

    def _message_bubble(self, message: QuestionChatMessage, question: ReadinessQuestion) -> QWidget:
        if message.role == "user":
            return self._user_bubble(message.content)
        return self._assistant_bubble(message.content)

    def _assistant_bubble(
        self,
        text: str,
        *,
        quote: str = "",
        question: ReadinessQuestion | None = None,
        section: str = "",
    ) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
        bubble.setMaximumWidth(_CHAT_WIDTH - 120)
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
        layout.setSpacing(10)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(app_font(13))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(label)
        if quote:
            if section:
                source = QLabel(f"Источник: раздел «{section}»")
                source.setWordWrap(True)
                source.setFont(app_font(11, QFont.Weight.DemiBold))
                source.setStyleSheet("color: #08745F; background: transparent;")
                layout.addWidget(source)
            quote_label = QLabel(f"«{quote}»")
            quote_label.setWordWrap(True)
            quote_label.setFont(app_font(12))
            quote_label.setStyleSheet(
                """
                color: #53625E;
                background: rgba(8,116,95,0.05);
                border: 1px solid rgba(8,116,95,0.12);
                border-radius: 12px;
                padding: 10px;
                """
            )
            layout.addWidget(quote_label)
        if question is not None:
            why = QPushButton("Почему я спрашиваю?")
            why.setCursor(Qt.CursorShape.PointingHandCursor)
            why.setFlat(True)
            why.setStyleSheet("QPushButton { color: #08745F; text-align: left; background: transparent; }")
            reason = QLabel(_reason_text(question))
            reason.setWordWrap(True)
            reason.setVisible(False)
            reason.setFont(app_font(12))
            reason.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            why.clicked.connect(lambda _checked=False, item=reason: item.setVisible(not item.isVisible()))
            layout.addWidget(why)
            layout.addWidget(reason)
            question_label = QLabel(_question_text(question))
            question_label.setWordWrap(True)
            question_label.setFont(app_font(14, QFont.Weight.DemiBold))
            question_label.setStyleSheet("color: #06483D; background: transparent;")
            layout.addWidget(question_label)
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
        bubble.setMaximumWidth(_CHAT_WIDTH - 140)
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

    def _quick_answers(self, question: ReadinessQuestion) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        max_chip_width = _CHAT_WIDTH - 72
        for option in self._quick_answer_options(question):
            row = QHBoxLayout()
            row.setSpacing(8)
            btn = _quick_answer_button(option, max_chip_width=max_chip_width, primary=True)
            btn.clicked.connect(
                lambda _checked=False, qid=self._chat_target_question_id(question), value=option: self.chat_message_requested.emit(
                    qid,
                    value,
                )
            )
            row.addWidget(btn)
            row.addStretch(1)
            layout.addLayout(row)

        secondary = QHBoxLayout()
        for option in ("Пока неизвестно", "Для этой функции не требуется"):
            btn = QPushButton(option)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFlat(True)
            btn.setStyleSheet("QPushButton { color: #6B7773; background: transparent; text-align: left; }")
            btn.clicked.connect(
                lambda _checked=False, qid=self._chat_target_question_id(question), value=option: self.chat_message_requested.emit(
                    qid,
                    value,
                )
            )
            secondary.addWidget(btn)
        secondary.addStretch(1)
        layout.addLayout(secondary)
        return wrap

    def _quick_answer_options(self, question: ReadinessQuestion) -> list[str]:
        if self._chat is not None:
            for message in reversed(self._chat.messages):
                if message.role != "assistant":
                    continue
                quick = message.structured.get("quickAnswers") if isinstance(message.structured, dict) else None
                if isinstance(quick, list):
                    values = [str(item).strip() for item in quick if str(item).strip()]
                    if values:
                        return values[:5]
        return _primary_options(question)

    def _input_bar(self, question: ReadinessQuestion) -> QWidget:
        wrap = QWidget()
        wrap.setFixedWidth(_CHAT_WIDTH - 36)
        wrap.setStyleSheet("background: transparent;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        self._input = ChatInput()
        send = QPushButton("➤")
        send.setFixedSize(46, 46)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(
            """
            QPushButton {
                background: #08745F;
                color: #FFFFFF;
                border: none;
                border-radius: 23px;
                font-size: 18px;
            }
            QPushButton:hover { background: #0A806A; }
            """
        )

        def submit() -> None:
            if self._input is None:
                return
            text = self._input.toPlainText().strip()
            if text:
                self.chat_message_requested.emit(self._chat_target_question_id(question), text)
                self._input.clear()

        self._input.send_requested.connect(submit)
        send.clicked.connect(submit)
        row.addWidget(self._input, 1)
        row.addWidget(send)
        return wrap

    def _chat_matches(self, question: ReadinessQuestion) -> bool:
        if self._chat is None:
            return False
        return self._chat.question_id == question.question_id or (
            bool(self._chat.function_id) and self._chat.function_id == question.function_id
        )

    def _chat_target_question_id(self, question: ReadinessQuestion) -> str:
        if self._chat_matches(question) and self._chat is not None:
            return self._chat.question_id
        return question.question_id

    def _change_proposal(self, change: ReadinessChange) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            """
            QFrame {
                background: rgba(8,116,95,0.04);
                border: 1px solid rgba(8,116,95,0.18);
                border-radius: 16px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        tag = QLabel("Предлагаемая редакция")
        tag.setFont(app_font(12, QFont.Weight.DemiBold))
        tag.setStyleSheet("color: #08745F; background: transparent;")
        layout.addWidget(tag)
        section = QLabel(f"Раздел документа: {change.target_block_id or 'связанный пункт'}")
        section.setFont(app_font(12))
        section.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(section)
        text = QLabel(change.after or change.reason)
        text.setWordWrap(True)
        text.setFont(app_font(13))
        text.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(text)
        source = QPushButton("Показать исходный текст")
        source.setFlat(True)
        source.setCursor(Qt.CursorShape.PointingHandCursor)
        source.setStyleSheet("QPushButton { color: #08745F; background: transparent; text-align: left; }")
        before = QLabel(change.before or "Исходный текст не найден.")
        before.setWordWrap(True)
        before.setVisible(False)
        before.setFont(app_font(12))
        before.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        source.clicked.connect(lambda _checked=False, item=before: item.setVisible(not item.isVisible()))
        layout.addWidget(source)
        layout.addWidget(before)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        edit = QPushButton("Изменить")
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.setStyleSheet(_secondary_button_qss())
        edit.clicked.connect(lambda _checked=False, change_id=change.change_id, after=change.after: self.change_decision_requested.emit(change_id, "edited", after))
        accept = QPushButton("Подтвердить формулировку")
        accept.setCursor(Qt.CursorShape.PointingHandCursor)
        accept.setStyleSheet(_primary_button_qss())
        accept.clicked.connect(lambda _checked=False, change_id=change.change_id: self.change_decision_requested.emit(change_id, "accepted", ""))
        buttons.addWidget(edit)
        buttons.addWidget(accept)
        layout.addLayout(buttons)
        return card

    def _footer_actions(self) -> QWidget:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        actions = QHBoxLayout(wrap)
        actions.setContentsMargins(0, 0, 0, 0)
        back = QPushButton("Вернуться позже")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setStyleSheet(_secondary_button_qss())
        back.clicked.connect(self.back_requested.emit)
        actions.addWidget(back)
        actions.addStretch(1)
        finalize = QPushButton("Создать копию регламента")
        finalize.setCursor(Qt.CursorShape.PointingHandCursor)
        finalize.setEnabled(bool(self._result and self._result.changes))
        finalize.setStyleSheet(_primary_button_qss())
        finalize.clicked.connect(self.finalize_requested.emit)
        actions.addWidget(finalize)
        return wrap

    def _progress_panel(self, questions: list[ReadinessQuestion], current: ReadinessQuestion | None) -> QWidget:
        card = _soft_card()
        card.setFixedWidth(_PANEL_WIDTH)
        card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        title = QLabel("Прогресс уточнения")
        title.setFont(app_font(15, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(title)
        done = [question for question in questions if question.answered]
        count = QLabel(f"Уточнено параметров: {len(done)}")
        count.setFont(app_font(12))
        count.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(count)
        progress = QProgressBar()
        progress.setRange(0, max(len(questions), 1))
        progress.setValue(len(done))
        progress.setTextVisible(False)
        progress.setFixedHeight(5)
        progress.setStyleSheet(_progress_qss())
        layout.addWidget(progress)
        layout.addWidget(_group_label("Готово"))
        for question in done[:3]:
            layout.addWidget(_topic_row(_field_title(question.target_field), done=True))
        if current is not None:
            layout.addWidget(_group_label("Сейчас"))
            layout.addWidget(_topic_row(_field_title(current.target_field), active=True))
        upcoming = [question for question in questions if not question.answered and question is not current][:3]
        if upcoming:
            layout.addWidget(_group_label("Далее"))
            for question in upcoming:
                layout.addWidget(_topic_row(_field_title(question.target_field)))
        hint = QLabel(
            "LLM задаёт следующий вопрос по мере необходимости; внутренний список параметров не является фиксированным сценарием."
        )
        hint.setWordWrap(True)
        hint.setFont(app_font(11))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(hint)
        return card

    def _change_for_question(self, question: ReadinessQuestion) -> ReadinessChange | None:
        if self._result is None:
            return None
        for change in reversed(self._result.changes):
            if change.source.get("questionId") == question.question_id:
                return change
        return None

    def _first_context_quote(self) -> str:
        if self._chat is None or not isinstance(self._chat.context, dict):
            return ""
        question = self._chat.context.get("question") or {}
        evidence = question.get("sourceEvidence") or {}
        quote = evidence.get("quote") if isinstance(evidence, dict) else ""
        if quote:
            return str(quote)[:320]
        blocks = self._chat.context.get("affectedBlocks") or []
        if blocks and isinstance(blocks[0], dict):
            return str(blocks[0].get("text") or "")[:320]
        return ""

    def _first_context_section(self) -> str:
        if self._chat is None or not isinstance(self._chat.context, dict):
            return ""
        question = self._chat.context.get("question") or {}
        evidence = question.get("sourceEvidence") or {}
        section = evidence.get("section") if isinstance(evidence, dict) else ""
        if section:
            return str(section)
        blocks = self._chat.context.get("affectedBlocks") or []
        if blocks and isinstance(blocks[0], dict):
            return str(blocks[0].get("section") or "")
        return ""

    def _context_function_title(self, question: ReadinessQuestion) -> str:
        if self._chat is not None and isinstance(self._chat.context, dict):
            function = self._chat.context.get("function") or {}
            title = function.get("title") if isinstance(function, dict) else ""
            if title:
                return str(title)
        return _function_title(question)


def _soft_card() -> QFrame:
    card = QFrame()
    card.setObjectName("SoftCard")
    card.setStyleSheet(
        """
        QFrame#SoftCard {
            background: #FFFFFF;
            border: 1px solid rgba(16,24,23,0.08);
            border-radius: 18px;
        }
        """
    )
    return card


def _group_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(app_font(11, QFont.Weight.DemiBold))
    label.setStyleSheet("color: #08745F; background: transparent;")
    return label


def _topic_row(text: str, *, done: bool = False, active: bool = False) -> QLabel:
    prefix = "✓" if done else "•"
    label = QLabel(f"{prefix}  {text}")
    label.setWordWrap(True)
    label.setFont(app_font(12, QFont.Weight.DemiBold if active else QFont.Weight.Normal))
    color = "#08745F" if done or active else "#6B7773"
    label.setStyleSheet(f"color: {color}; background: transparent;")
    return label


def _quick_answer_button(text: str, *, max_chip_width: int, primary: bool) -> QPushButton:
    btn = QPushButton()
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    btn.setStyleSheet(_chip_qss(primary=primary))
    btn.setFont(app_font(12))
    metrics = QFontMetrics(btn.font())
    wrapped = _wrap_button_text(text, metrics, max_chip_width - 28)
    lines = max(1, wrapped.count("\n") + 1)
    width = min(max_chip_width, max(metrics.horizontalAdvance(line) for line in wrapped.splitlines()) + 28)
    btn.setText(wrapped)
    btn.setFixedWidth(max(120, width))
    btn.setFixedHeight(34 + (lines - 1) * 18)
    return btn


def _wrap_button_text(text: str, metrics: QFontMetrics, max_text_width: int) -> str:
    words = text.split()
    if not words or metrics.horizontalAdvance(text) <= max_text_width:
        return text
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and metrics.horizontalAdvance(candidate) > max_text_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines)


def _primary_options(question: ReadinessQuestion) -> list[str]:
    if question.target_field == "trigger":
        return [
            "По поручению руководителя",
            "При появлении новой инициативы",
            "По установленному графику",
            "Другой вариант",
        ]
    if question.options:
        generic = {"указать ответ", "не требуется", "пока неизвестно", "другой вариант"}
        options = [item for item in question.options if item and item.casefold() not in generic]
        if options:
            return options[:4]
    return ["По поручению руководителя", "По установленному графику", "Другой вариант"]


def _chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def _function_title(question: ReadinessQuestion) -> str:
    if ":" in question.reason:
        return question.reason.split(":", 1)[0].strip(" —")
    return "уточняемая функция"


def _question_text(question: ReadinessQuestion) -> str:
    if question.target_field == "trigger":
        return "Когда и при каком событии должна начинаться эта работа?"
    return question.question


def _reason_text(question: ReadinessQuestion) -> str:
    if question.target_field == "trigger":
        return "Без события запуска агент не сможет определить, когда нужно начинать эту работу."
    return question.reason or "Это уточнение нужно, чтобы агент мог выполнить процесс без ошибок."


def _gap_explanation(question: ReadinessQuestion) -> str:
    return {
        "trigger": "Но в этом месте не сказано, при каком событии сотрудник должен начинать работу.",
        "inputs": "Но в этом месте не перечислены входные данные, которые нужны агенту для выполнения действия.",
        "result": "Но в этом месте не описан проверяемый результат, который должен получить агент.",
        "recipient": "Но в этом месте не указано, кому передаётся результат или проблема.",
        "deadline": "Но в этом месте не указан срок выполнения.",
        "errors": "Но в этом месте не описано, что делать при ошибке или невозможности выполнить действие.",
        "approval": "Но в этом месте не указано, требуется ли подтверждение человека.",
        "control": "Но в этом месте не описано, как проверить правильность выполнения.",
    }.get(
        question.target_field,
        "Но в этом месте не хватает правила, без которого агент не сможет выполнить действие однозначно.",
    )


def _field_title(field: str) -> str:
    return {
        "actor": "Ответственный",
        "trigger": "Событие запуска",
        "inputs": "Входные данные",
        "action": "Действие",
        "system": "Система",
        "result": "Результат",
        "recipient": "Получатель",
        "conditions": "Условия",
        "branches": "Варианты результата",
        "deadline": "Срок выполнения",
        "errors": "Обработка ошибки",
        "escalation": "Эскалация",
        "approval": "Подтверждение",
        "permissions": "Права доступа",
        "restrictions": "Ограничения",
        "control": "Контроль",
        "kpi": "KPI",
    }.get(field, field)


def _primary_button_qss() -> str:
    return """
    QPushButton {
        background: #08745F;
        color: #FFFFFF;
        border: none;
        border-radius: 12px;
        padding: 9px 14px;
    }
    QPushButton:hover { background: #0A806A; }
    QPushButton:disabled {
        background: rgba(8,116,95,0.25);
        color: rgba(255,255,255,0.85);
    }
    """


def _secondary_button_qss() -> str:
    return """
    QPushButton {
        background: #FFFFFF;
        color: #08745F;
        border: 1px solid rgba(8,116,95,0.18);
        border-radius: 12px;
        padding: 9px 14px;
    }
    QPushButton:hover { background: rgba(8,116,95,0.05); }
    """


def _chip_qss(*, primary: bool) -> str:
    bg = "rgba(8,116,95,0.06)" if primary else "#FFFFFF"
    return f"""
    QPushButton {{
        background: {bg};
        color: #06483D;
        border: 1px solid rgba(8,116,95,0.14);
        border-radius: 10px;
        padding: 8px 10px;
    }}
    QPushButton:hover {{ background: rgba(8,116,95,0.10); }}
    """


def _progress_qss() -> str:
    return """
    QProgressBar {
        background: rgba(8,116,95,0.10);
        border: none;
        border-radius: 3px;
    }
    QProgressBar::chunk {
        background: #08745F;
        border-radius: 3px;
    }
    """


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child is not None:
            _clear_layout(child)
