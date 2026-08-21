from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import Card, ClarificationQuestion
from app.ui.styles import card_qss, input_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


class PassportPage(QWidget):
    continue_requested = Signal()
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card: Card | None = None
        self._field_edits: dict[str, QLineEdit] = {}

        title = QLabel("Паспорт агента")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._chat = QPlainTextEdit()
        self._chat.setReadOnly(True)
        self._chat.setPlaceholderText("Здесь появится диалог паспорта…")

        chat_frame = QFrame()
        chat_frame.setStyleSheet(card_qss("PassportChat", radius=16))
        chat_lay = QVBoxLayout(chat_frame)
        chat_lay.setContentsMargins(12, 12, 12, 12)
        chat_lay.addWidget(self._chat)

        self._fields_host = QVBoxLayout()
        self._fields_host.setSpacing(8)
        fields_inner = QWidget()
        fields_inner.setLayout(self._fields_host)
        fields_scroll = QScrollArea()
        fields_scroll.setWidgetResizable(True)
        fields_scroll.setFrameShape(QFrame.Shape.NoFrame)
        fields_scroll.setWidget(fields_inner)
        fields_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        fields_frame = QFrame()
        fields_frame.setStyleSheet(card_qss("PassportFields", radius=16))
        fields_lay = QVBoxLayout(fields_frame)
        fields_lay.setContentsMargins(12, 12, 12, 12)
        fields_heading = QLabel("Поля паспорта")
        fields_heading.setFont(app_font(14, QFont.Weight.DemiBold))
        fields_lay.addWidget(fields_heading)
        fields_lay.addWidget(fields_scroll, 1)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(chat_frame, 3)
        body.addWidget(fields_frame, 2)

        back = QPushButton("Назад")
        back.setStyleSheet(secondary_button_qss(radius=12))
        back.clicked.connect(self.cancelled.emit)
        self._next_btn = QPushButton("К playbook →")
        self._next_btn.setStyleSheet(primary_button_qss(radius=12))
        self._next_btn.clicked.connect(self.continue_requested.emit)

        self._advance = QLabel("")
        self._advance.setFont(app_font(13))
        self._advance.setStyleSheet(
            "color: #06483D; background: #F3FAF7; border: 1px solid rgba(8,116,95,0.18);"
            "border-radius: 10px; padding: 10px 14px;"
        )
        self._advance.setWordWrap(True)
        self._advance.hide()

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(back)
        actions.addWidget(self._next_btn)
        self._action_buttons = (back, self._next_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self._advance)
        layout.addLayout(body, 1)
        layout.addLayout(actions)

    def set_actions_enabled(self, enabled: bool) -> None:
        for btn in self._action_buttons:
            btn.setEnabled(enabled)
        if enabled:
            self._next_btn.setText("К playbook →")
        else:
            self._next_btn.setText("Собираем сценарий…")

    def show_advance(self, text: str) -> None:
        if text.strip():
            self._advance.setText(text)
            self._advance.show()
        else:
            self._advance.hide()

    def set_card(self, card: Card) -> None:
        self._card = card
        self._advance.hide()
        self._chat.clear()
        passport = card.passport
        lines = [
            f"**{passport.title or card.title}**",
            passport.summary or "",
            f"Цель: {passport.goal}",
            f"Инструменты: {', '.join(passport.tools)}",
        ]
        for q in passport.questions:
            ans = passport.answered.get(q.id, "")
            lines.append(f"Q: {q.question}")
            if ans:
                lines.append(f"A: {ans}")
        self._chat.setPlainText("\n".join(line for line in lines if line))

        while self._fields_host.count():
            item = self._fields_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._field_edits.clear()
        for field in passport.fields:
            row = QVBoxLayout()
            label = QLabel(field.label)
            label.setFont(app_font(12, QFont.Weight.DemiBold))
            edit = QLineEdit(field.value)
            edit.setStyleSheet(input_qss())
            self._field_edits[field.id] = edit
            wrap = QWidget()
            wrap.setLayout(row)
            row.addWidget(label)
            row.addWidget(edit)
            self._fields_host.addWidget(wrap)
        if not passport.fields:
            empty = QLabel("Поля будут заполнены после анализа.")
            empty.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._fields_host.addWidget(empty)

    def apply_field_values(self, card: Card) -> Card:
        for field in card.passport.fields:
            edit = self._field_edits.get(field.id)
            if edit is not None:
                field.value = edit.text().strip()
        return card

    def open_questions(self) -> list[ClarificationQuestion]:
        if self._card is None:
            return []
        return list(self._card.passport.questions)
