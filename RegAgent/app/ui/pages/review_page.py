from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.models import Card
from app.ui.styles import ghost_button_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class ReviewPage(QWidget):
    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card: Card | None = None

        title = QLabel("Проверка регламента")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._subtitle = QLabel("")
        self._subtitle.setFont(app_font(14))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._subtitle.setWordWrap(True)

        self._advance = QLabel("")
        self._advance.setFont(app_font(13))
        self._advance.setStyleSheet(
            "color: #06483D; background: #F3FAF7; border: 1px solid rgba(8,116,95,0.18);"
            "border-radius: 10px; padding: 10px 14px;"
        )
        self._advance.setWordWrap(True)
        self._advance.hide()

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMinimumHeight(320)
        self._text.setFont(app_font(12))

        back = QPushButton("Назад")
        back.setStyleSheet(secondary_button_qss(radius=12))
        back.clicked.connect(self.cancelled.emit)

        self._next_btn = QPushButton("Продолжить → функции")
        self._next_btn.setStyleSheet(primary_button_qss(radius=12))
        self._next_btn.clicked.connect(self.confirmed.emit)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(back)
        actions.addWidget(self._next_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(self._subtitle)
        layout.addWidget(self._advance)
        layout.addWidget(self._text, 1)
        layout.addLayout(actions)
        self._action_buttons = (back, self._next_btn)

    def set_actions_enabled(self, enabled: bool) -> None:
        for btn in self._action_buttons:
            btn.setEnabled(enabled)
        if enabled:
            self._next_btn.setText("Продолжить → функции")
        else:
            self._next_btn.setText("Анализируем функции…")

    def show_advance(self, text: str) -> None:
        if text.strip():
            self._advance.setText(text)
            self._advance.show()
        else:
            self._advance.hide()

    def set_card(self, card: Card) -> None:
        self._card = card
        self._advance.hide()
        name = Path(card.regulation_path).name if card.regulation_path else "регламент"
        self._subtitle.setText(f"Файл: {name}. Проверьте текст перед анализом функций.")
        self._text.setPlainText(card.regulation_text or "")
