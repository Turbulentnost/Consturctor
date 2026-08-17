"""Паспорт ИИ-агента: чат слева, карточка справа."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QTextOption
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import AgentPassport, AgentSuggestion, PassportSession
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_USER_MENU_RESERVE = 320
_ATTACH_SUFFIXES = {".doc", ".docx", ".pdf", ".md", ".txt"}
_ATTACH_FILTER = "Документы (*.doc *.docx *.pdf *.md *.txt)"
_INPUT_FONT_SIZE = 12
_INPUT_MAX_LINES = 5
_SEND_SIZE = 32
_AUTONOMY_LEVEL = 1
_AUTONOMY_LEVEL_TEXT = (
    "Уровень 1: генерация текста, инструменты чтения и human-in-the-loop; "
    "все остальные операции выполняются только после подтверждения человека."
)
_PRIMARY_FIELDS = (
    ("name", "Название"),
    ("goal", "Цель"),
    ("trigger", "Триггер"),
)
_SECONDARY_FIELDS = (
    ("receives", "Получает"),
    ("checks", "Проверяет"),
    ("decisions", "Принимает решения"),
    ("can_autonomous", "Может самостоятельно"),
    ("needs_human_approval", "Требует подтверждения человека"),
    ("forbidden", "Не может"),
    ("result", "Результат"),
)
_FIELD_ROWS = _PRIMARY_FIELDS + _SECONDARY_FIELDS
_FIELD_LABELS = {key: label for key, label in _FIELD_ROWS}

_INPUT_SHELL = """
QFrame#ComposerShell {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 18px;
}
QFrame#ComposerShell:disabled { background: #F4F7F6; }
"""
_INPUT_STYLE = """
QTextEdit {
    background: transparent;
    color: #101817;
    border: none;
    padding: 8px 4px 8px 12px;
    selection-background-color: #08745F;
}
QTextEdit:disabled { color: #9DB3AD; }
"""
_SEND_BUTTON = """
QPushButton {
    background: #08745F;
    color: #FFFFFF;
    border: none;
    border-radius: 16px;
    font-size: 16px;
    font-weight: 700;
}
QPushButton:hover { background: #0A8670; }
QPushButton:pressed { background: #06483D; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_ATTACH_BUTTON = """
QToolButton {
    background: transparent;
    color: #8B9692;
    border: none;
    border-radius: 16px;
    font-size: 16px;
    padding: 0;
}
QToolButton:hover { color: #06483D; background: rgba(8,116,95,0.08); }
QToolButton:disabled { color: #C5D0CC; }
"""
_FILE_CHIP = """
QFrame#FileChip {
    background: #F3F7F5;
    border: 1px solid rgba(16,24,23,0.10);
    border-radius: 10px;
}
QFrame#FileChip QLabel {
    background: transparent;
    border: none;
    color: #06483D;
}
QToolButton#FileChipRemove {
    background: transparent;
    border: none;
    color: #8B9692;
    font-size: 12px;
    padding: 0;
}
QToolButton#FileChipRemove:hover { color: #06483D; }
"""


class AgentPassportPage(QWidget):
    back_requested = Signal()
    finished_requested = Signal(object)
    draft_requested = Signal(object)
    answer_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._suggestion: AgentSuggestion | None = None
        self._session: PassportSession | None = None
        self._qa_history: list[tuple[str, str, list[str]]] = []
        self._current_question: dict | None = None
        self._busy = False
        self._chat_stick_to_bottom = True
        self._pending_files: list[str] = []

        self._title = QLabel("Паспорт ИИ-агента")
        self._title.setFont(app_font(28, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._title.setWordWrap(True)

        self._subtitle = QLabel("Агент уточнит пробелы в паспорте в чате слева.")
        self._subtitle.setFont(app_font(13))
        self._subtitle.setWordWrap(True)
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        header_text = QVBoxLayout()
        header_text.setContentsMargins(0, 0, _USER_MENU_RESERVE, 0)
        header_text.setSpacing(4)
        header_text.addWidget(self._title)
        header_text.addWidget(self._subtitle)

        self._back = QPushButton("Назад")
        self._back.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back.setFixedHeight(36)
        self._back.setStyleSheet(_secondary_btn_qss())
        self._back.clicked.connect(self.back_requested.emit)
        back_row = QHBoxLayout()
        back_row.setContentsMargins(0, 0, 0, 0)
        back_row.addStretch(1)
        back_row.addWidget(self._back, 0, Qt.AlignmentFlag.AlignRight)

        header = QVBoxLayout()
        header.setSpacing(8)
        header.addLayout(header_text)
        header.addLayout(back_row)

        self._passport_card = self._build_passport_card()
        self._chat_card = self._build_chat_card()

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addWidget(self._chat_card, 3)
        columns.addWidget(self._passport_card, 2)

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
        self._pending_files = []
        self._sync_files_chips()
        self._busy = True
        self._title.setText(suggestion.title or "Паспорт ИИ-агента")
        self._subtitle.setText(suggestion.description or "Собираю паспорт и уточняющие вопросы…")
        self._render_passport(AgentPassport(autonomy_level=_AUTONOMY_LEVEL))
        self._render_chat(loading=True, loading_text="Собираю черновик паспорта агента…")
        self._finish_btn.setEnabled(False)
        self._set_status("Агент готовит паспорт…")
        self.draft_requested.emit(suggestion)

    def apply_session(self, session: PassportSession) -> None:
        self._busy = False
        self._session = session
        self._set_composer_enabled(True)
        self._apply_passport(session.passport)

    def show_error(self, message: str) -> None:
        self._busy = False
        self._set_composer_enabled(True)
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
        for key, label in _PRIMARY_FIELDS:
            self._add_field_row(key, label, prominent=True)
        self._add_autonomy_row()
        for key, label in _SECONDARY_FIELDS:
            self._add_field_row(key, label, prominent=False)
        self._fields_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(host)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        layout.addWidget(scroll, 1)
        return card

    def _add_field_row(self, key: str, label: str, *, prominent: bool) -> None:
        row = QFrame()
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(12, 8, 12, 8)
        row_layout.setSpacing(2)
        title = QLabel(label)
        title.setFont(app_font(10, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        value = QLabel("—")
        value.setFont(app_font(13 if prominent else 12, QFont.Weight.DemiBold if prominent else QFont.Weight.Normal))
        value.setWordWrap(True)
        value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        value.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        row_layout.addWidget(title)
        row_layout.addWidget(value)
        self._fields_layout.addWidget(row)
        self._field_value_labels[key] = value
        self._field_row_frames[key] = row

    def _add_autonomy_row(self) -> None:
        row = QFrame()
        row.setStyleSheet("QFrame { background: #EEF7F3; border: 1px solid #CDE6DC; border-radius: 12px; }")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(4)
        title = QLabel("Уровень автономности")
        title.setFont(app_font(10, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #06483D; background: transparent;")
        level = QLabel(f"Уровень {_AUTONOMY_LEVEL}")
        level.setFont(app_font(14, QFont.Weight.DemiBold))
        level.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        desc = QLabel(_AUTONOMY_LEVEL_TEXT)
        desc.setFont(app_font(11))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        row_layout.addWidget(title)
        row_layout.addWidget(level)
        row_layout.addWidget(desc)
        self._fields_layout.addWidget(row)
        self._autonomy_frame = row

    def _build_chat_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("PassportChatCard")
        card.setMinimumWidth(420)
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

        self._composer = QFrame()
        self._composer.setObjectName("ComposerShell")
        self._composer.setStyleSheet(_INPUT_SHELL)
        self._files_host = QWidget()
        self._files_host.setStyleSheet("background: transparent;")
        self._files_host.hide()
        self._files_row = QHBoxLayout(self._files_host)
        self._files_row.setContentsMargins(10, 8, 10, 0)
        self._files_row.setSpacing(8)
        self._input = _ComposerInput()
        self._input.setPlaceholderText("Напишите ответ…")
        self._input.setFont(app_font(_INPUT_FONT_SIZE))
        self._input.setStyleSheet(_INPUT_STYLE + scroll_bar_qss())
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._input.setAcceptRichText(False)
        self._input.setTabChangesFocus(True)
        self._input.textChanged.connect(self._resize_input)
        self._input.submit_requested.connect(self._on_send)
        self._attach = QToolButton()
        self._attach.setText("📎")
        self._attach.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach.setFixedSize(_SEND_SIZE, _SEND_SIZE)
        self._attach.setStyleSheet(_ATTACH_BUTTON)
        self._attach.setToolTip("Прикрепить файлы (doc, docx, pdf, md, txt)")
        self._attach.clicked.connect(self._pick_files)
        self._send_btn = QPushButton("↑")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFixedSize(_SEND_SIZE, _SEND_SIZE)
        self._send_btn.setStyleSheet(_SEND_BUTTON)
        self._send_btn.setToolTip("Отправить")
        self._send_btn.clicked.connect(self._on_send)
        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(4, 4, 8, 4)
        composer_row.setSpacing(4)
        composer_row.addWidget(self._input, 1)
        composer_row.addWidget(self._attach, 0, Qt.AlignmentFlag.AlignBottom)
        composer_row.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)
        composer_inner = QVBoxLayout(self._composer)
        composer_inner.setContentsMargins(0, 0, 0, 0)
        composer_inner.setSpacing(0)
        composer_inner.addWidget(self._files_host)
        composer_inner.addLayout(composer_row)
        self._resize_input()
        composer_hint = QLabel("Enter — отправить • Shift + Enter — новая строка")
        composer_hint.setFont(app_font(11))
        composer_hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(self._composer)
        layout.addWidget(composer_hint)
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
            self._set_composer_enabled(False)
            self._scroll_chat_to_bottom()
            return

        if not self._qa_history and not current_prompt:
            self._messages_layout.addWidget(
                self._assistant_bubble(
                    "Уточнений нет — паспорт заполнен. Можно нажать «Далее · план»."
                )
            )
        for prompt, answer, files in self._qa_history:
            self._messages_layout.addWidget(self._assistant_bubble(prompt))
            self._messages_layout.addWidget(self._user_bubble(answer, files))
        if current_prompt:
            self._messages_layout.addWidget(self._assistant_bubble(current_prompt))
        self._messages_layout.addStretch(1)
        self._set_composer_enabled(not self._busy and bool(current_prompt))
        self._scroll_chat_to_bottom()

    def _assistant_bubble(self, text: str) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        bubble = QFrame()
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
        layout.setContentsMargins(12, 10, 12, 10)
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(app_font(11))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(label)
        row.addWidget(bubble, 1)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _user_bubble(self, text: str, files: list[str] | None = None) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        bubble = QFrame()
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
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)
        if files:
            chips = QHBoxLayout()
            chips.setContentsMargins(0, 0, 0, 0)
            chips.setSpacing(6)
            for path in files:
                chips.addWidget(self._file_chip(Path(path).name, removable=False), 0)
            chips.addStretch(1)
            layout.addLayout(chips)
        if text:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setFont(app_font(11))
            label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
            layout.addWidget(label)
        row.addWidget(bubble, 1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _on_send(self) -> None:
        if self._busy or self._session is None or not self._current_question:
            return
        answer = self._input.toPlainText().strip()
        files = list(self._pending_files)
        if not answer and not files:
            self._set_status("Введите ответ или прикрепите файл.", error=True)
            return
        prompt = str(self._current_question.get("prompt") or "Уточните поле паспорта")
        field = str(self._current_question.get("field") or "")
        qid = str(self._current_question.get("id") or "")
        self._qa_history.append((prompt, answer, files))
        self._input.clear()
        self._pending_files = []
        self._sync_files_chips()
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
        self.answer_requested.emit({"answers": answers, "files": files})

    def current_session(self) -> PassportSession | None:
        return self._session

    def _on_finish(self) -> None:
        if self._session is None:
            return
        if self._session.passport.missing_fields:
            self._set_status("Сначала ответьте на все уточнения в чате.", error=True)
            return
        self.finished_requested.emit(self._session)

    def _pick_files(self) -> None:
        if not self._attach.isEnabled():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, "Прикрепить файлы", "", _ATTACH_FILTER)
        skipped: list[str] = []
        added = False
        for path in paths:
            file_path = Path(path)
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in _ATTACH_SUFFIXES:
                skipped.append(file_path.name)
                continue
            value = str(file_path)
            if value not in self._pending_files:
                self._pending_files.append(value)
                added = True
        self._sync_files_chips()
        if skipped:
            QMessageBox.information(
                self,
                "Файлы",
                "Можно прикрепить только doc, docx, pdf, md, txt.",
            )
        elif not added and paths:
            QMessageBox.information(self, "Файлы", "Эти файлы уже прикреплены.")

    def _remove_pending_file(self, path: str) -> None:
        self._pending_files = [item for item in self._pending_files if item != path]
        self._sync_files_chips()

    def _sync_files_chips(self) -> None:
        while self._files_row.count():
            item = self._files_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._pending_files:
            self._files_host.hide()
            self._resize_input()
            return
        for path in self._pending_files:
            self._files_row.addWidget(
                self._file_chip(Path(path).name, removable=True, on_remove=lambda p=path: self._remove_pending_file(p))
            )
        self._files_row.addStretch(1)
        self._files_host.show()
        self._resize_input()

    def _file_chip(self, name: str, *, removable: bool, on_remove=None) -> QWidget:
        chip = QFrame()
        chip.setObjectName("FileChip")
        chip.setStyleSheet(_FILE_CHIP)
        row = QHBoxLayout(chip)
        row.setContentsMargins(8, 4, 6, 4)
        row.setSpacing(4)
        title = QLabel(_short_attachment_name(name))
        title.setFont(app_font(11))
        row.addWidget(title)
        if removable:
            remove = QToolButton()
            remove.setObjectName("FileChipRemove")
            remove.setText("✕")
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setFixedSize(16, 16)
            if on_remove is not None:
                remove.clicked.connect(on_remove)
            row.addWidget(remove)
        return chip

    def _resize_input(self) -> None:
        metrics = self._input.fontMetrics()
        line = max(metrics.lineSpacing(), 16)
        doc_h = int(self._input.document().size().height()) + 16
        height = min(max(doc_h, line + 16), line * _INPUT_MAX_LINES + 16)
        self._input.setFixedHeight(height)
        files_h = self._files_host.sizeHint().height() if self._files_host.isVisible() else 0
        self._composer.setFixedHeight(max(height + 8 + files_h, _SEND_SIZE + 8 + files_h))

    def _set_composer_enabled(self, enabled: bool) -> None:
        self._input.setEnabled(enabled)
        self._send_btn.setEnabled(enabled)
        self._attach.setEnabled(enabled)

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


class _ComposerInput(QTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)


def _short_attachment_name(name: str, keep: int = 6) -> str:
    path = Path(name)
    stem = path.stem.replace(" ", "_")
    suffix = path.suffix.lower()
    if len(stem) <= keep:
        return f"{stem}{suffix}"
    return f"{stem[:keep]}...{suffix}"


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
