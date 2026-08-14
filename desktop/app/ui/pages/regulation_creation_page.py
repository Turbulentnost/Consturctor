from __future__ import annotations

import re
import shutil
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QPainter,
    QPainterPath,
    QPixmap,
    QTextCursor,
    QTextOption,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import RegulationCreationSession
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_LOGO_PATH = Path(__file__).resolve().parents[1] / "temp" / "logo.png"
_AVATAR_SIZE = 36
_CHAT_MIN_WIDTH = 640
_CHAT_MAX_WIDTH = 1400
_CHAT_WIDTH_RATIO = 0.68
_USER_MENU_RESERVE = 320
_ATTACH_SUFFIXES = {".doc", ".docx", ".pdf", ".md", ".txt"}
_ATTACH_FILTER = "Документы (*.doc *.docx *.pdf *.md *.txt)"

_INPUT_SHELL = """
QFrame#ComposerShell {
    background: #FFFFFF;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 18px;
}
QFrame#ComposerShell:disabled {
    background: #F4F7F6;
}
"""
_INPUT_STYLE = """
QTextEdit {
    background: transparent;
    color: #101817;
    border: none;
    padding: 8px 4px 8px 12px;
    selection-background-color: #08745F;
}
QTextEdit:disabled {
    color: #9DB3AD;
}
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
_QUICK_ANSWER_BUTTON = """
QPushButton {
    background: #FFFFFF;
    color: #06483D;
    border: 1px solid rgba(16,24,23,0.12);
    border-radius: 14px;
    padding: 0 12px;
    text-align: left;
}
QPushButton:hover { background: #F4F7F6; border-color: #08745F; }
QPushButton:disabled { background: #F4F7F6; color: #9DB3AD; }
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
_FILE_CHIP_USER = """
QFrame#FileChip {
    background: rgba(255,255,255,0.16);
    border: 1px solid rgba(255,255,255,0.28);
    border-radius: 10px;
}
QFrame#FileChip QLabel {
    background: transparent;
    border: none;
    color: #FFFFFF;
}
"""
_INPUT_FONT_SIZE = 12
_INPUT_MAX_LINES = 5
_SEND_SIZE = 32


def _short_attachment_name(name: str, keep: int = 6) -> str:
    path = Path(name)
    stem = path.stem.replace(" ", "_")
    suffix = path.suffix.lower()
    if len(stem) <= keep:
        return f"{stem}{suffix}"
    return f"{stem[:keep]}...{suffix}"


def _split_message_attachments(text: str, structured: dict | None = None) -> tuple[str, list[str]]:
    names: list[str] = []
    data = structured if isinstance(structured, dict) else {}
    raw = data.get("attachments") or []
    for item in raw:
        if isinstance(item, dict):
            value = str(item.get("name") or "").strip()
            if value:
                names.append(value)
        else:
            value = str(item or "").strip()
            if value:
                names.append(value)
    if names:
        body_lines = []
        for line in (text or "").splitlines():
            if line.strip().startswith("📎"):
                continue
            body_lines.append(line)
        return "\n".join(body_lines).strip(), names

    body_lines: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("📎"):
            for part in stripped.lstrip("📎").split(","):
                value = part.strip()
                if value:
                    names.append(value)
            continue
        body_lines.append(line)
    return "\n".join(body_lines).strip(), names


def _extract_proposal_text(message: str) -> str:
    text = (message or "").strip()
    if not text:
        return ""
    match = re.search(
        r"Предлагаю\s+так\s*:\s*(.*?)(?:\n\s*\n\s*Оставить это или переделать\s*\??\s*$|$)",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()
    # Fallback: take the middle block between question and the keep/redo prompt.
    parts = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if len(parts) >= 2:
        for part in parts[1:]:
            if part.lower().startswith("оставить это или переделать"):
                continue
            if part.lower().startswith("вопрос"):
                continue
            cleaned = re.sub(r"^Предлагаю\s+так\s*:\s*", "", part, flags=re.IGNORECASE).strip()
            if cleaned:
                return re.sub(r"\s+", " ", cleaned).strip()
    return ""


class RegulationCreationPage(QWidget):
    message_requested = Signal(str, str, list)
    finished_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._session: RegulationCreationSession | None = None
        self._think_expanded = False
        self._thinking_text = ""
        self._live_status = ""
        self._auto_scroll_enabled = True
        self._programmatic_scroll = False
        self._size_bucket = -1
        self._pending_files: list[str] = []
        self._messages_layout = QVBoxLayout()
        self._messages_layout.setContentsMargins(0, 0, 0, 0)
        self._messages_layout.setSpacing(10)
        self._chat_column = QWidget()
        self._chat_column.setStyleSheet("background: transparent;")
        self._chat_column.setLayout(self._messages_layout)
        self._chat_column.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_row = QHBoxLayout(content)
        content_row.setContentsMargins(14, 14, 14, 14)
        content_row.setSpacing(0)
        content_row.addStretch(1)
        content_row.addWidget(self._chat_column, 0, Qt.AlignmentFlag.AlignTop)
        content_row.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(content)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())
        self._scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        self._composer = QFrame()
        self._composer.setObjectName("ComposerShell")
        self._composer.setStyleSheet(_INPUT_SHELL)
        self._composer.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._files_host = QWidget()
        self._files_host.setStyleSheet("background: transparent;")
        self._files_host.hide()
        self._files_row = QHBoxLayout(self._files_host)
        self._files_row.setContentsMargins(10, 8, 10, 0)
        self._files_row.setSpacing(8)
        self._input = _ComposerInput()
        self._input.setPlaceholderText("Напишите ответ...")
        self._input.setFont(app_font(_INPUT_FONT_SIZE))
        self._input.setStyleSheet(_INPUT_STYLE + scroll_bar_qss())
        self._input.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._input.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._input.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self._input.setAcceptRichText(False)
        self._input.setTabChangesFocus(True)
        self._input.textChanged.connect(self._resize_input)
        self._input.submit_requested.connect(self._submit)
        self._attach = QToolButton()
        self._attach.setText("📎")
        self._attach.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach.setFixedSize(_SEND_SIZE, _SEND_SIZE)
        self._attach.setStyleSheet(_ATTACH_BUTTON)
        self._attach.setToolTip("Прикрепить файлы (doc, docx, pdf, md, txt)")
        self._attach.clicked.connect(self._pick_files)
        self._send = QPushButton("↑")
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setFixedSize(_SEND_SIZE, _SEND_SIZE)
        self._send.setStyleSheet(_SEND_BUTTON)
        self._send.setToolTip("Отправить")
        self._send.clicked.connect(self._submit)
        composer_row = QHBoxLayout()
        composer_row.setContentsMargins(4, 4, 8, 4)
        composer_row.setSpacing(4)
        composer_row.addWidget(self._input, 1)
        composer_row.addWidget(self._attach, 0, Qt.AlignmentFlag.AlignBottom)
        composer_row.addWidget(self._send, 0, Qt.AlignmentFlag.AlignBottom)
        composer_inner = QVBoxLayout(self._composer)
        composer_inner.setContentsMargins(0, 0, 0, 0)
        composer_inner.setSpacing(0)
        composer_inner.addWidget(self._files_host)
        composer_inner.addLayout(composer_row)
        self._resize_input()
        composer_wrap = QHBoxLayout()
        composer_wrap.setContentsMargins(14, 0, 14, 0)
        composer_wrap.setSpacing(0)
        composer_wrap.addStretch(1)
        composer_wrap.addWidget(self._composer, 0)
        composer_wrap.addStretch(1)
        composer_hint = QLabel("Enter — отправить • Shift + Enter — новая строка")
        composer_hint.setFont(app_font(11))
        composer_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        composer_hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        composer_footer = QVBoxLayout()
        composer_footer.setContentsMargins(0, 0, 0, 8)
        composer_footer.setSpacing(6)
        composer_footer.addLayout(composer_wrap)
        composer_footer.addWidget(composer_hint)
        title = QLabel("Создание регламента")
        title.setFont(app_font(26, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setWordWrap(True)
        self._title = title
        self._force_create = QPushButton("Создать принудительно")
        self._force_create.setCursor(Qt.CursorShape.PointingHandCursor)
        self._force_create.setFixedHeight(36)
        self._force_create.setFont(app_font(12, QFont.Weight.DemiBold))
        self._force_create.setStyleSheet(_SECONDARY_BUTTON)
        self._force_create.setEnabled(False)
        self._force_create.clicked.connect(self._force_create_now)
        self._header_inline = True
        self._title_row = QHBoxLayout()
        self._title_row.setContentsMargins(0, 0, 0, 0)
        self._title_row.setSpacing(14)
        self._title_row.addWidget(self._title, 0, Qt.AlignmentFlag.AlignVCenter)
        self._title_row.addWidget(self._force_create, 0, Qt.AlignmentFlag.AlignVCenter)
        self._title_row.addStretch(1)
        self._force_create_host = QWidget()
        self._force_create_host.setStyleSheet("background: transparent;")
        self._force_create_row = QHBoxLayout(self._force_create_host)
        self._force_create_row.setContentsMargins(0, 0, 0, 0)
        self._force_create_row.setSpacing(0)
        self._force_create_host.hide()
        subtitle = QLabel("Ответьте на вопросы, и ИИ подготовит регламент в стиле ваших документов")
        subtitle.setFont(app_font(13))
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        header_block = QVBoxLayout()
        header_block.setContentsMargins(0, 0, _USER_MENU_RESERVE, 0)
        header_block.setSpacing(8)
        header_block.addLayout(self._title_row)
        header_block.addWidget(self._force_create_host)
        header_block.addWidget(subtitle)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(header_block)
        layout.addWidget(self._scroll, 1)
        layout.addLayout(composer_footer)
        self._apply_chat_width(force=True)
        self._update_header_layout(force=True)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_chat_width()
        self._update_header_layout()

    def _chat_width(self) -> int:
        available = max(0, self.width() - 28)
        return max(_CHAT_MIN_WIDTH, min(_CHAT_MAX_WIDTH, int(available * _CHAT_WIDTH_RATIO)))

    def _bubble_max_width(self) -> int:
        return max(420, self._chat_width() - _AVATAR_SIZE - 28)

    def _update_header_layout(self, *, force: bool = False) -> None:
        available = max(0, self.width() - _USER_MENU_RESERVE)
        title_w = self._title.sizeHint().width()
        button_w = self._force_create.sizeHint().width()
        want_inline = (title_w + self._title_row.spacing() + button_w) <= available
        if not force and want_inline == self._header_inline:
            return
        self._header_inline = want_inline
        self._title_row.removeWidget(self._force_create)
        self._force_create_row.removeWidget(self._force_create)
        while self._force_create_row.count():
            item = self._force_create_row.takeAt(0)
            del item
        if want_inline:
            self._title_row.insertWidget(1, self._force_create, 0, Qt.AlignmentFlag.AlignVCenter)
            self._force_create_host.hide()
        else:
            self._force_create_row.addWidget(self._force_create, 0, Qt.AlignmentFlag.AlignLeft)
            self._force_create_row.addStretch(1)
            self._force_create_host.show()
        self._force_create.show()

    def _apply_chat_width(self, *, force: bool = False) -> None:
        width = self._chat_width()
        if not force and width == self._size_bucket:
            return
        prev = self._size_bucket
        self._size_bucket = width
        self._chat_column.setFixedWidth(width)
        self._composer.setFixedWidth(width)
        self._resize_input()
        if prev > 0 and self._session is not None:
            self._render_messages()

    def set_session(self, session: RegulationCreationSession) -> None:
        self._session = session
        if session.status != "generating":
            self._thinking_text = ""
            self._live_status = ""
        self._render_messages()
        generating = session.status == "generating"
        finalized = session.status == "finalized"
        enabled = not generating and not finalized
        self._input.setEnabled(enabled)
        self._send.setEnabled(enabled)
        self._attach.setEnabled(enabled)
        self._composer.setEnabled(enabled)
        has_user_input = any(message.role == "user" for message in session.messages)
        self._force_create.setEnabled(has_user_input and enabled)
        if not enabled:
            self._pending_files.clear()
            self._sync_files_chips()

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
            body, attachments = _split_message_attachments(message.content, message.structured)
            self._messages_layout.addWidget(
                self._bubble(
                    body,
                    user=message.role == "user",
                    quick_answers=quick_answers,
                    attachments=attachments,
                    source_text=body,
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
        if self._session is None or not self._send.isEnabled():
            return
        text = self._input.toPlainText().strip()
        files = list(self._pending_files)
        if not text and not files:
            return
        self._input.clear()
        self._input.setPlaceholderText("Напишите ответ...")
        self._pending_files.clear()
        self._sync_files_chips()
        self._resize_input()
        self.message_requested.emit(self._session.draft_id, text, files)

    def _pick_files(self) -> None:
        if not self._attach.isEnabled():
            return
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "Файлы для анализа",
            "",
            f"{_ATTACH_FILTER};;Все файлы (*)",
        )
        if not paths:
            return
        added = 0
        skipped: list[str] = []
        for path in paths:
            file_path = Path(path)
            if not file_path.is_file():
                continue
            suffix = file_path.suffix.lower()
            if suffix not in _ATTACH_SUFFIXES:
                skipped.append(file_path.name)
                continue
            value = str(file_path)
            if value not in self._pending_files:
                self._pending_files.append(value)
                added += 1
        self._sync_files_chips()
        self._resize_input()
        if skipped:
            QMessageBox.information(
                self,
                "Файлы",
                "Поддерживаются только: doc, docx, pdf, md, txt.\n"
                f"Пропущены: {', '.join(skipped)}",
            )
        elif added == 0 and paths:
            QMessageBox.information(self, "Файлы", "Эти файлы уже прикреплены.")

    def _remove_pending_file(self, path: str) -> None:
        self._pending_files = [item for item in self._pending_files if item != path]
        self._sync_files_chips()
        self._resize_input()

    def _sync_files_chips(self) -> None:
        while self._files_row.count():
            item = self._files_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._pending_files:
            self._files_host.hide()
            return
        for path in self._pending_files:
            self._files_row.addWidget(
                self._file_chip(Path(path).name, removable=True, on_remove=lambda p=path: self._remove_pending_file(p))
            )
        self._files_row.addStretch(1)
        self._files_host.show()

    def _file_chip(
        self,
        name: str,
        *,
        user_bubble: bool = False,
        removable: bool = False,
        on_remove=None,
    ) -> QFrame:
        chip = QFrame()
        chip.setObjectName("FileChip")
        chip.setStyleSheet(_FILE_CHIP_USER if user_bubble else _FILE_CHIP)
        row = QHBoxLayout(chip)
        row.setContentsMargins(8, 4, 8, 4)
        row.setSpacing(6)
        icon = QLabel("📄")
        icon.setFont(app_font(12))
        icon.setStyleSheet("background: transparent; border: none;")
        title = QLabel(_short_attachment_name(name))
        title.setFont(app_font(11, QFont.Weight.DemiBold))
        title.setToolTip(name)
        title.setStyleSheet("background: transparent; border: none;")
        row.addWidget(icon)
        row.addWidget(title)
        if removable and on_remove is not None:
            remove = QToolButton()
            remove.setObjectName("FileChipRemove")
            remove.setText("×")
            remove.setCursor(Qt.CursorShape.PointingHandCursor)
            remove.setFixedSize(18, 18)
            remove.clicked.connect(on_remove)
            row.addWidget(remove)
        return chip

    def _resize_input(self) -> None:
        metrics = self._input.fontMetrics()
        line_h = max(metrics.lineSpacing(), metrics.height())
        top = self._input.contentsMargins().top() + 8
        bottom = self._input.contentsMargins().bottom() + 8
        min_h = line_h + top + bottom
        max_h = line_h * _INPUT_MAX_LINES + top + bottom
        doc = self._input.document()
        doc.setTextWidth(max(self._input.viewport().width(), 40))
        needed = int(doc.size().height()) + top + bottom
        height = max(min_h, min(max_h, needed))
        self._input.setFixedHeight(height)
        files_h = self._files_host.sizeHint().height() if self._files_host.isVisible() else 0
        shell_h = height + 8 + files_h
        self._composer.setFixedHeight(max(shell_h, _SEND_SIZE + 8 + files_h))
        at_max = needed > max_h
        self._input.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if at_max else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def _force_create_now(self) -> None:
        if self._session is None or not self._force_create.isEnabled():
            return
        self.message_requested.emit(
            self._session.draft_id,
            "Создай регламент принудительно по текущей информации. "
            "Если каких-то данных не хватает, используй разумные типовые формулировки и явно отметь, что это предположение.",
            [],
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

    def _send_quick_answer(self, answer: str, source_text: str = "") -> None:
        if self._session is None:
            return
        value = answer.strip()
        if not value:
            return
        if value.lower().startswith("передел"):
            proposal = _extract_proposal_text(source_text)
            self._input.setPlainText(proposal)
            self._input.setPlaceholderText("Измените предложенный вариант и отправьте...")
            self._resize_input()
            self._input.setFocus()
            cursor = self._input.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self._input.setTextCursor(cursor)
            return
        self._input.clear()
        self.message_requested.emit(self._session.draft_id, value, [])

    def _assistant_avatar(self) -> QLabel:
        avatar = QLabel()
        avatar.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
        avatar.setStyleSheet("background: transparent;")
        canvas = QPixmap(_AVATAR_SIZE, _AVATAR_SIZE)
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(0.5, 0.5, _AVATAR_SIZE - 1, _AVATAR_SIZE - 1)
        path = QPainterPath()
        path.addEllipse(rect)
        painter.fillPath(path, QColor("#E7F4F0"))
        if _LOGO_PATH.exists():
            logo = QPixmap(str(_LOGO_PATH))
            if not logo.isNull():
                painter.setClipPath(path)
                scaled = logo.scaled(
                    _AVATAR_SIZE - 6,
                    _AVATAR_SIZE - 6,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                x = (_AVATAR_SIZE - scaled.width()) // 2
                y = (_AVATAR_SIZE - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
        painter.end()
        avatar.setPixmap(canvas)
        return avatar

    def _bubble(
        self,
        text: str,
        *,
        user: bool,
        quick_answers: list[str] | None = None,
        attachments: list[str] | None = None,
        source_text: str = "",
    ) -> QWidget:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        if user:
            row.addStretch(1)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        who = QLabel("Вы" if user else "ИИ-ассистент")
        who.setFont(app_font(11))
        who.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        who.setAlignment(Qt.AlignmentFlag.AlignRight if user else Qt.AlignmentFlag.AlignLeft)
        column.addWidget(who)

        bubble = QFrame()
        bubble.setObjectName("MessageBubble")
        bubble.setMaximumWidth(self._bubble_max_width())
        bubble.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        if user:
            bubble.setStyleSheet(
                """
                QFrame#MessageBubble {
                    background: #08745F;
                    border: none;
                    border-radius: 16px;
                }
                QFrame#MessageBubble > QLabel {
                    background: transparent;
                    border: none;
                    color: #FFFFFF;
                }
                """
            )
        else:
            bubble.setStyleSheet(
                """
                QFrame#MessageBubble {
                    background: #FFFFFF;
                    border: 1px solid rgba(16,24,23,0.10);
                    border-radius: 16px;
                }
                QFrame#MessageBubble > QLabel {
                    background: transparent;
                    border: none;
                    color: #101817;
                }
                """
            )
        layout = QVBoxLayout(bubble)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)
        if text.strip():
            label = QLabel(text)
            label.setWordWrap(True)
            label.setFont(app_font(13))
            label.setStyleSheet("background: transparent; border: none;")
            layout.addWidget(label)
        files = attachments or []
        if files:
            chips = QHBoxLayout()
            chips.setContentsMargins(0, 0, 0, 0)
            chips.setSpacing(6)
            for name in files:
                chips.addWidget(self._file_chip(name, user_bubble=user), 0)
            chips.addStretch(1)
            layout.addLayout(chips)
        answers = quick_answers or []
        if answers:
            actions = QVBoxLayout()
            actions.setContentsMargins(0, 6, 0, 0)
            actions.setSpacing(8)
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(8)
            used = 0
            max_row = max(220, self._bubble_max_width() - 28)
            for answer in answers:
                btn = self._quick_answer_button(answer, source_text=source_text or text)
                need = btn.sizeHint().width() + (8 if used else 0)
                if used and used + need > max_row:
                    row.addStretch(1)
                    actions.addLayout(row)
                    row = QHBoxLayout()
                    row.setContentsMargins(0, 0, 0, 0)
                    row.setSpacing(8)
                    used = 0
                row.addWidget(btn, 0)
                used += need
            row.addStretch(1)
            actions.addLayout(row)
            layout.addLayout(actions)
        column.addWidget(bubble, 0, Qt.AlignmentFlag.AlignRight if user else Qt.AlignmentFlag.AlignLeft)

        if not user:
            row.addWidget(self._assistant_avatar(), 0, Qt.AlignmentFlag.AlignTop)
        body = QWidget()
        body.setStyleSheet("background: transparent;")
        body.setLayout(column)
        body.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        row.addWidget(body, 0, Qt.AlignmentFlag.AlignTop)
        if not user:
            row.addStretch(1)

        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        wrap.setLayout(row)
        return wrap

    def _quick_answer_button(self, answer: str, *, source_text: str) -> QPushButton:
        btn = QPushButton()
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(34)
        btn.setFont(app_font(12, QFont.Weight.DemiBold))
        btn.setStyleSheet(_QUICK_ANSWER_BUTTON)
        btn.setToolTip(answer)
        btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        max_w = min(360, max(180, self._bubble_max_width() - 48))
        metrics = QFontMetrics(btn.font())
        text_w = max(40, max_w - 28)
        elided = metrics.elidedText(answer, Qt.TextElideMode.ElideRight, text_w)
        btn.setText(elided)
        btn.setMaximumWidth(max_w)
        btn.clicked.connect(
            lambda _checked=False, value=answer, src=source_text: self._send_quick_answer(value, src)
        )
        return btn

    def _working_block(self) -> QWidget:
        return self._bubble(self._live_status or "Задаю вопрос...", user=False)

    def _document_result_block(self) -> QWidget:
        card = QFrame()
        card.setObjectName("ResultCard")
        card.setMaximumWidth(self._bubble_max_width())
        card.setStyleSheet(
            """
            QFrame#ResultCard {
                background: #FFFFFF;
                border: 1px solid rgba(8,116,95,0.18);
                border-radius: 16px;
            }
            QFrame#ResultCard QLabel {
                border: none;
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
        row.setSpacing(10)
        row.addSpacing(_AVATAR_SIZE)
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
        card.setObjectName("ThinkCard")
        card.setMaximumWidth(self._bubble_max_width())
        card.setStyleSheet(
            """
            QFrame#ThinkCard {
                background: #FFFFFF;
                border: 1px solid rgba(8,116,95,0.14);
                border-radius: 16px;
            }
            QFrame#ThinkCard QLabel {
                background: transparent;
                border: none;
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
        row.setSpacing(10)
        row.addWidget(self._assistant_avatar(), 0, Qt.AlignmentFlag.AlignTop)
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


class _ComposerInput(QTextEdit):
    submit_requested = Signal()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)
