from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget

from app.api_client import RegulationCreationSession
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_INPUT_STYLE = """
QTextEdit {
    background: #FFFFFF;
    color: #101817;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 16px;
    padding: 12px 14px;
    selection-background-color: #08745F;
}
QTextEdit:disabled {
    background: #F4F7F6;
    color: #9DB3AD;
}
"""
_PRIMARY_BUTTON = """
QPushButton {
    background: #08745F;
    color: #FFFFFF;
    border: none;
    border-radius: 16px;
    padding: 0 22px;
}
QPushButton:hover { background: #0A8670; }
QPushButton:disabled { background: #A8C8BF; color: #EAF7F3; }
"""
_SECONDARY_BUTTON = """
QPushButton {
    background: #FFFFFF;
    color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 14px;
    padding: 0 14px;
}
QPushButton:hover { background: #F4F7F6; border-color: #08745F; }
QPushButton:disabled { background: #F4F7F6; color: #9DB3AD; }
"""


class RegulationCreationPage(QWidget):
    message_requested = Signal(str, str)
    finished_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: RegulationCreationSession | None = None
        self._think_expanded = False
        self._thinking_text = ""
        self._live_status = ""
        self._auto_scroll_enabled = True
        self._programmatic_scroll = False
        self._messages_layout = QVBoxLayout()
        self._messages_layout.setContentsMargins(14, 14, 14, 14)
        self._messages_layout.setSpacing(10)
        content = QWidget()
        content.setLayout(self._messages_layout)
        content.setStyleSheet("background: transparent;")
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(content)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        self._input = QTextEdit()
        self._input.setFixedHeight(76)
        self._input.setPlaceholderText("Напишите ответ...")
        self._input.setFont(app_font(13))
        self._input.setStyleSheet(_INPUT_STYLE + scroll_bar_qss())
        self._send = QPushButton("Отправить")
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setFixedHeight(48)
        self._send.setMinimumWidth(132)
        self._send.setFont(app_font(12, QFont.Weight.DemiBold))
        self._send.setStyleSheet(_PRIMARY_BUTTON)
        self._send.clicked.connect(self._submit)
        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(12)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._send, 0, Qt.AlignmentFlag.AlignBottom)
        title = QLabel("Создание регламента")
        title.setFont(app_font(26, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._force_create = QPushButton("Создать принудительно")
        self._force_create.setCursor(Qt.CursorShape.PointingHandCursor)
        self._force_create.setFixedHeight(36)
        self._force_create.setFont(app_font(12, QFont.Weight.DemiBold))
        self._force_create.setStyleSheet(_SECONDARY_BUTTON)
        self._force_create.setEnabled(False)
        self._force_create.clicked.connect(self._force_create_now)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(14)
        header.addWidget(title, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self._force_create, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        subtitle = QLabel("Ответьте на вопросы, и ИИ подготовит регламент в стиле ваших документов")
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(header)
        layout.addWidget(subtitle)
        layout.addWidget(self._scroll, 1)
        layout.addLayout(input_row)

    def set_session(self, session: RegulationCreationSession) -> None:
        self._session = session
        if session.status != "generating":
            self._thinking_text = ""
            self._live_status = ""
        self._render_messages()
        generating = session.status == "generating"
        finalized = session.status == "finalized"
        self._input.setEnabled(not generating and not finalized)
        self._send.setEnabled(not generating and not finalized)
        has_user_input = any(message.role == "user" for message in session.messages)
        self._force_create.setEnabled(has_user_input and not generating and not finalized)

    def _render_messages(self) -> None:
        should_scroll = self._should_auto_scroll()
        while self._messages_layout.count():
            item = self._messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if self._session is None:
            return
        can_answer = self._session.status not in {"generating", "finalized"}
        for index, message in enumerate(self._session.messages):
            quick_answers = []
            if message.role != "user" and can_answer and index == len(self._session.messages) - 1:
                raw = message.structured.get("quickAnswers") if isinstance(message.structured, dict) else []
                quick_answers = [str(item) for item in (raw or []) if str(item).strip()]
            self._messages_layout.addWidget(
                self._bubble(
                    message.content,
                    user=message.role == "user",
                    quick_answers=quick_answers,
                )
            )
        if self._session.status == "generating":
            if self._thinking_text:
                self._messages_layout.addWidget(self._think_block())
            else:
                self._messages_layout.addWidget(self._working_block())
        if self._session.status == "finalized" and self._has_result_document():
            self._messages_layout.addWidget(self._document_result_block())
        self._messages_layout.addStretch(1)
        if should_scroll:
            self._scroll_to_bottom()

    def _submit(self) -> None:
        if self._session is None:
            return
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self._input.setPlaceholderText("Напишите ответ...")
        self.message_requested.emit(self._session.draft_id, text)

    def _force_create_now(self) -> None:
        if self._session is None or not self._force_create.isEnabled():
            return
        self.message_requested.emit(
            self._session.draft_id,
            "Создай регламент принудительно по текущей информации. "
            "Если каких-то данных не хватает, используй разумные типовые формулировки и явно отметь, что это предположение.",
        )

    def append_stream_event(self, event_type: str, text: str) -> None:
        if event_type == "thinking" and text:
            self._thinking_text += text
            self._think_expanded = True
            self._render_messages()
        elif event_type == "assistant" and text:
            self._live_status = "Агент формирует следующий вопрос..."
            self._render_messages()
        elif event_type == "status":
            self._live_status = _creation_status_text(text)
            self._render_messages()

    def _send_quick_answer(self, answer: str) -> None:
        if self._session is None:
            return
        value = answer.strip()
        if not value:
            return
        if value.lower().startswith("передел"):
            self._input.setPlaceholderText("Напишите, как нужно переделать предложенный вариант...")
            self._input.setFocus()
            return
        self._input.clear()
        self.message_requested.emit(self._session.draft_id, value)

    def _bubble(self, text: str, *, user: bool, quick_answers: list[str] | None = None) -> QWidget:
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
        answers = quick_answers or []
        if answers:
            actions = QHBoxLayout()
            actions.setContentsMargins(0, 6, 0, 0)
            actions.setSpacing(8)
            for answer in answers:
                btn = QPushButton(answer)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.setFixedHeight(34)
                btn.setFont(app_font(12, QFont.Weight.DemiBold))
                btn.setStyleSheet(_SECONDARY_BUTTON)
                btn.clicked.connect(lambda _checked=False, value=answer: self._send_quick_answer(value))
                actions.addWidget(btn)
            actions.addStretch(1)
            layout.addLayout(actions)
        row.addWidget(bubble)
        if not user:
            row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _working_block(self) -> QWidget:
        return self._bubble(self._live_status or "Задаю вопрос...", user=False)

    def _document_result_block(self) -> QWidget:
        card = QFrame()
        card.setMaximumWidth(720)
        card.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid rgba(8,116,95,0.18);
                border-radius: 16px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        title = QLabel("Документ создан")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #08745F; background: transparent;")
        layout.addWidget(title)
        path = Path(self._session.result_document_path) if self._session else Path()
        name = path.name or "regulation.docx"
        hint = QLabel(name)
        hint.setWordWrap(True)
        hint.setFont(app_font(12))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout.addWidget(hint)
        preview_text = self._document_preview_text()
        if preview_text:
            preview = QLabel(preview_text)
            preview.setWordWrap(True)
            preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            preview.setFont(app_font(12))
            preview.setStyleSheet(
                """
                QLabel {
                    color: #101817;
                    background: #F8FBFA;
                    border: 1px solid rgba(16,24,23,0.08);
                    border-radius: 12px;
                    padding: 10px 12px;
                }
                """
            )
            layout.addWidget(preview)

        actions = QHBoxLayout()
        actions.addStretch(1)
        download = QPushButton("Скачать")
        download.setCursor(Qt.CursorShape.PointingHandCursor)
        download.setFixedHeight(36)
        download.setFont(app_font(12, QFont.Weight.DemiBold))
        download.setStyleSheet(_SECONDARY_BUTTON)
        download.setEnabled(self._document_path() is not None)
        download.clicked.connect(self._download_document)
        preview = QPushButton("Просмотреть")
        preview.setCursor(Qt.CursorShape.PointingHandCursor)
        preview.setFixedHeight(36)
        preview.setFont(app_font(12, QFont.Weight.DemiBold))
        preview.setStyleSheet(_PRIMARY_BUTTON)
        preview.setEnabled(self._document_path() is not None)
        preview.clicked.connect(self._preview_document)
        actions.addWidget(download)
        actions.addWidget(preview)
        layout.addLayout(actions)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(card)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _has_result_document(self) -> bool:
        if self._session is None:
            return False
        return bool(
            self._session.result_document
            or self._session.result_document_path
            or self._session.result_regulation is not None
        )

    def _document_preview_text(self) -> str:
        if self._session is None:
            return ""
        document = self._session.result_document
        if document:
            lines = [str(document.get("title") or "Регламент").strip()]
            for section in document.get("sections") or []:
                if not isinstance(section, dict):
                    continue
                number = str(section.get("number") or "").strip()
                title = str(section.get("title") or "").strip()
                heading = f"{number} {title}".strip()
                if heading:
                    lines.extend(["", heading])
                for paragraph in section.get("paragraphs") or []:
                    text = str(paragraph or "").strip()
                    if text:
                        lines.append(text)
                for item in section.get("items") or []:
                    text = str(item or "").strip()
                    if text:
                        lines.append(f"- {text}")
            return "\n".join(line for line in lines if line or lines)
        result = self._session.result_regulation
        if result is None:
            return ""
        parts = [fragment.text.strip() for fragment in result.fragments if fragment.text.strip()]
        return "\n\n".join(parts)

    def _document_path(self) -> Path | None:
        if self._session is None or not self._session.result_document_path:
            return None
        path = Path(self._session.result_document_path)
        return path if path.is_file() else None

    def _preview_document(self) -> None:
        path = self._document_path()
        if path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _download_document(self) -> None:
        path = self._document_path()
        if path is None:
            return
        target, _filter = QFileDialog.getSaveFileName(self, "Сохранить регламент", path.name)
        if not target:
            return
        shutil.copy2(path, target)

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

    def _should_auto_scroll(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        return self._auto_scroll_enabled or (bar.maximum() - bar.value()) <= 24

    def _scroll_to_bottom(self) -> None:
        def apply() -> None:
            bar = self._scroll.verticalScrollBar()
            self._programmatic_scroll = True
            bar.setValue(bar.maximum())
            self._programmatic_scroll = False
            self._auto_scroll_enabled = True

        QTimer.singleShot(0, apply)

    def _on_scroll_value_changed(self, _value: int) -> None:
        if self._programmatic_scroll:
            return
        bar = self._scroll.verticalScrollBar()
        self._auto_scroll_enabled = (bar.maximum() - bar.value()) <= 24


def _creation_status_text(status: str) -> str:
    return {
        "generating": "Задаю вопрос...",
        "stream_unavailable_polling": "Агент продолжает работу, ожидаю следующий вопрос...",
    }.get(status, "Агент готовит следующий вопрос...")
