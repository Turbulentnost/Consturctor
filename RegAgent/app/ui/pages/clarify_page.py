from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import ClarificationQuestion, UiSpec
from app.ui.styles import card_qss, input_qss, primary_button_qss, radio_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


class ClarifyPage(QWidget):
    submitted = Signal(dict)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec: UiSpec | None = None
        self._fields: dict[str, tuple[QButtonGroup | None, QComboBox | None, QLineEdit | None]] = {}

        self._title = QLabel("Уточнение взаимодействия")
        self._title.setFont(app_font(28, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._title.setContentsMargins(0, 0, 280, 0)

        self._subtitle = QLabel("Агенту нужны ответы, чтобы спроектировать кнопки")
        self._subtitle.setFont(app_font(14))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._subtitle.setWordWrap(True)
        self._subtitle.setContentsMargins(0, 0, 280, 0)

        self._form_host = QVBoxLayout()
        self._form_host.setSpacing(12)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner.setLayout(self._form_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        submit = QPushButton("Продолжить")
        submit.setCursor(Qt.CursorShape.PointingHandCursor)
        submit.setFixedHeight(42)
        submit.setFont(app_font(13, QFont.Weight.DemiBold))
        submit.setStyleSheet(primary_button_qss(radius=12))
        submit.clicked.connect(self._on_submit)

        back = QPushButton("Назад")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFixedHeight(42)
        back.setFont(app_font(13, QFont.Weight.DemiBold))
        back.setStyleSheet(secondary_button_qss(radius=12))
        back.clicked.connect(self.cancelled.emit)
        self._action_buttons = (back, submit)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 8, 0, 0)
        actions.addStretch(1)
        actions.addWidget(back)
        actions.addWidget(submit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self._title)
        root.addWidget(self._subtitle)
        root.addWidget(scroll, 1)
        root.addLayout(actions)

    def set_actions_enabled(self, enabled: bool) -> None:
        for btn in self._action_buttons:
            btn.setEnabled(enabled)

    def set_spec(self, spec: UiSpec) -> None:
        self.set_spec_questions(spec.needs_clarification)

    def set_spec_questions(self, questions: list[ClarificationQuestion]) -> None:
        self._spec = None
        while self._form_host.count():
            item = self._form_host.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._fields.clear()
        for q in questions:
            self._form_host.addWidget(self._question_block(q))
        self._form_host.addStretch(1)

    def _question_block(self, q: ClarificationQuestion) -> QWidget:
        box = QFrame()
        box.setObjectName("ClarifyCard")
        box.setStyleSheet(card_qss("ClarifyCard", radius=16))
        layout = QVBoxLayout(box)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        label = QLabel(q.question)
        label.setFont(app_font(14, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        label.setWordWrap(True)
        layout.addWidget(label)

        group: QButtonGroup | None = None
        combo: QComboBox | None = None
        free: QLineEdit | None = None

        if q.options:
            group = QButtonGroup(box)
            for opt in q.options:
                rb = QRadioButton(opt)
                rb.setFont(app_font(13))
                rb.setCursor(Qt.CursorShape.PointingHandCursor)
                rb.setStyleSheet(radio_qss())
                layout.addWidget(rb)
                group.addButton(rb)
            if group.buttons():
                group.buttons()[0].setChecked(True)
        if q.allow_free_text:
            free = QLineEdit()
            free.setPlaceholderText("Свой вариант…")
            free.setFont(app_font(13))
            free.setFixedHeight(40)
            free.setStyleSheet(input_qss())
            layout.addWidget(free)

        self._fields[q.id] = (group, combo, free)
        return box

    def _on_submit(self) -> None:
        answers: dict[str, str] = {}
        for qid, (group, _combo, free) in self._fields.items():
            value = ""
            if group is not None:
                checked = group.checkedButton()
                if checked is not None:
                    value = checked.text()
            if free is not None and free.text().strip():
                value = free.text().strip()
            if value:
                answers[qid] = value
        self.submitted.emit(answers)
