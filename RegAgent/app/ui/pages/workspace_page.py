from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.attachment_text import stage_attachments
from app.models import Card
from app.storage.session_log import format_transcript, load_session_log, save_session_log
from app.tools.confirm_bridge import clear_confirm_bridge, install_confirm_bridge
from app.ui.agent_thread import AgentThreadController
from app.ui.styles import card_qss, ghost_button_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss
from app.ui.widgets.app_dialog import AppDialog
from app.ui.widgets.cursor_feed import (
    CursorFeedItem,
    format_tool_event,
    merge_stream_text,
    should_show_status,
    tool_header_title,
)
from app.ui.widgets.markdown_body import MarkdownBody
from app.ui.widgets.result_file_card import ResultFileCard, paths_from_result
from app.ui.widgets.status_chip import StatusChip


_ATTACH_SUFFIXES = {".doc", ".docx", ".pdf", ".md", ".txt", ".xlsx"}
_ATTACH_FILTER = "Документы (*.doc *.docx *.pdf *.md *.txt *.xlsx)"
_ATTACH_BUTTON = """
QToolButton {
    background: transparent;
    color: #8B9692;
    border: none;
    border-radius: 12px;
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


def _short_attachment_name(name: str, keep: int = 6) -> str:
    path = Path(name)
    stem = path.stem.replace(" ", "_")
    suffix = path.suffix.lower()
    if len(stem) <= keep:
        return f"{stem}{suffix}"
    return f"{stem[:keep]}...{suffix}"


_INPUT_MAX_LINES = 6


class _ComposerInput(QPlainTextEdit):
    submit_requested = Signal()
    height_sync_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.textChanged.connect(self.height_sync_requested.emit)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.submit_requested.emit()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.height_sync_requested.emit()


def _section(text: str) -> QLabel:
    label = QLabel(text)
    label.setFont(app_font(13, QFont.Weight.DemiBold))
    label.setStyleSheet("color: #06483D; background: transparent;")
    return label


def _side_item(text: str) -> QLabel:
    label = QLabel(f"• {text}")
    label.setFont(app_font(12, QFont.Weight.Medium))
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
    return label


def show_history_dialog(parent: QWidget | None, entries: list[tuple[str, str]]) -> None:
    transcript = format_transcript(entries)
    if not transcript:
        dialog = AppDialog(
            "История",
            message="В этой сессии пока нет сообщений.",
            parent=parent,
            primary="Закрыть",
        )
        dialog.exec()
        return
    dialog = AppDialog("История сессии", parent=parent, primary="Закрыть")
    dialog.resize(680, 520)
    dialog.add_body(MarkdownBody(transcript, font_size=13))
    dialog.exec()


class WorkspacePage(QWidget):
    back_requested = Signal()
    failed = Signal(str)
    agent_ready = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card: Card | None = None
        self._feed_items: list[CursorFeedItem] = []
        self._session_log: list[tuple[str, str]] = []
        self._live_assistant: CursorFeedItem | None = None
        self._live_thinking: CursorFeedItem | None = None
        self._last_agent_text = ""
        self._last_thinking_text = ""
        self._busy = False
        self._agent_ready_flag = False
        self._action_buttons: list[QPushButton] = []
        self._auto_quick_task = False
        self._restoring = False
        self._pending_files: list[str] = []

        self._confirm = install_confirm_bridge(self)
        self._agent_ctl: AgentThreadController | None = None

        self._title = QLabel("Агент")
        self._title.setFont(app_font(22, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._summary = QLabel("Напишите задачу — агент выполнит её сам.")
        self._summary.setWordWrap(True)
        self._summary.setFont(app_font(13))
        self._summary.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        back = QPushButton("← К списку")
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFlat(True)
        back.setFont(app_font(13, QFont.Weight.DemiBold))
        back.setStyleSheet(ghost_button_qss())
        back.clicked.connect(self._on_back)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        top_row.addWidget(back, 0, Qt.AlignmentFlag.AlignTop)
        title_col = QVBoxLayout()
        title_col.setContentsMargins(0, 0, 0, 0)
        title_col.setSpacing(4)
        title_col.addWidget(self._title)
        title_col.addWidget(self._summary)
        top_row.addLayout(title_col, 1)

        self._actions_host = QHBoxLayout()
        self._actions_host.setSpacing(8)

        self._feed_layout = QVBoxLayout()
        self._feed_layout.setContentsMargins(14, 14, 14, 14)
        self._feed_layout.setSpacing(10)
        self._feed_layout.addStretch(1)
        feed_inner = QWidget()
        feed_inner.setStyleSheet("background: transparent;")
        feed_inner.setLayout(self._feed_layout)
        self._feed_scroll = QScrollArea()
        self._feed_scroll.setWidgetResizable(True)
        self._feed_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._feed_scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )
        self._feed_scroll.setWidget(feed_inner)

        composer = QFrame()
        composer.setObjectName("ComposerBar")
        composer.setStyleSheet(
            """
            QFrame#ComposerBar {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 16px;
            }
            """
        )
        self._input = _ComposerInput()
        self._input.setPlaceholderText("Например: выполни типовую задачу по регламенту…")
        self._input.setFont(app_font(12))
        self._input.setStyleSheet(
            """
            QPlainTextEdit {
                background: transparent; color: #101817;
                border: none; padding: 8px 10px;
                selection-background-color: #08745F;
            }
            """
        )
        self._input.submit_requested.connect(self._send_chat)
        self._input.height_sync_requested.connect(self._resize_input)

        self._files_host = QWidget()
        self._files_host.setStyleSheet("background: transparent;")
        self._files_host.hide()
        self._files_row = QHBoxLayout(self._files_host)
        self._files_row.setContentsMargins(0, 0, 0, 4)
        self._files_row.setSpacing(6)

        self._attach_btn = QToolButton()
        self._attach_btn.setText("📎")
        self._attach_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach_btn.setFixedSize(36, 36)
        self._attach_btn.setStyleSheet(_ATTACH_BUTTON)
        self._attach_btn.setToolTip("Прикрепить файлы (doc, docx, pdf, md, txt, xlsx)")
        self._attach_btn.clicked.connect(self._pick_files)

        self._send_btn = QPushButton("Отправить")
        self._send_btn.setFixedHeight(36)
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._send_btn.setStyleSheet(primary_button_qss(radius=12, compact=True))
        self._send_btn.clicked.connect(self._send_chat)

        hint = QLabel("Enter — отправить · Shift+Enter — новая строка")
        hint.setFont(app_font(11))
        hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        input_row = QHBoxLayout()
        input_row.setContentsMargins(0, 0, 0, 0)
        input_row.setSpacing(8)
        input_row.addWidget(self._input, 1)
        input_row.addWidget(self._attach_btn, 0, Qt.AlignmentFlag.AlignBottom)
        input_row.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)

        composer_lay = QVBoxLayout(composer)
        composer_lay.setContentsMargins(12, 8, 12, 8)
        composer_lay.setSpacing(4)
        composer_lay.addWidget(self._files_host)
        composer_lay.addLayout(input_row)
        composer_lay.addWidget(hint)

        self._quick_btn = QPushButton("Запустить типовую задачу")
        self._quick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._quick_btn.setFixedHeight(40)
        self._quick_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._quick_btn.setStyleSheet(primary_button_qss(radius=14))
        self._quick_btn.clicked.connect(self._run_default_task)

        self._stop_btn = QPushButton("Остановить")
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.setFixedHeight(40)
        self._stop_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self._stop_btn.setStyleSheet(secondary_button_qss(radius=14))
        self._stop_btn.setEnabled(False)
        self._stop_btn.setToolTip("Прервать текущую работу агента")
        self._stop_btn.clicked.connect(self._stop_agent)

        task_row = QHBoxLayout()
        task_row.setSpacing(8)
        task_row.addWidget(self._quick_btn, 1)
        task_row.addWidget(self._stop_btn, 0)

        center_card = QFrame()
        center_card.setObjectName("AgentRunCard")
        center_card.setStyleSheet(card_qss("AgentRunCard", radius=18))
        center_layout = QVBoxLayout(center_card)
        center_layout.setContentsMargins(16, 14, 16, 14)
        center_layout.setSpacing(10)
        center_layout.addWidget(self._feed_scroll, 1)
        center_layout.addLayout(task_row, 0)
        center_layout.addWidget(composer, 0)

        side_card = QFrame()
        side_card.setObjectName("AgentRunSide")
        side_card.setStyleSheet(card_qss("AgentRunSide", radius=18))
        side_card.setFixedWidth(260)
        side_layout = QVBoxLayout(side_card)
        side_layout.setContentsMargins(16, 16, 16, 16)
        side_layout.setSpacing(10)
        side_layout.addWidget(_section("Как это работает"))
        for text in ("Вы даёте задачу", "Агент выполняет сценарий", "Вы получаете результат"):
            side_layout.addWidget(_side_item(text))
        side_layout.addWidget(_section("Статус"))
        self._status = StatusChip("Готов к работе", variant="success")
        self._status.setAlignment(Qt.AlignmentFlag.AlignLeft)
        side_layout.addWidget(self._status, 0, Qt.AlignmentFlag.AlignLeft)
        side_layout.addStretch(1)

        body = QHBoxLayout()
        body.setSpacing(14)
        body.addWidget(center_card, 1)
        body.addWidget(side_card, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addLayout(top_row)
        root.addLayout(self._actions_host)
        root.addLayout(body, 1)

        self._set_interactive(False)
        self._persist_timer = QTimer(self)
        self._persist_timer.setSingleShot(True)
        self._persist_timer.setInterval(250)
        self._persist_timer.timeout.connect(self._flush_session_log)
        self._restoring = False
        QTimer.singleShot(0, self._resize_input)

    def current_card_id(self) -> str:
        return self._card.id if self._card is not None else ""

    def history_entries(self) -> list[tuple[str, str]]:
        return list(self._session_log)

    def show_session_history(self) -> None:
        self._flush_session_log()
        show_history_dialog(self, self._session_log)

    def _ensure_agent_ctl(self) -> AgentThreadController:
        if self._agent_ctl is None:
            ctl = AgentThreadController(self)
            ctl.opened.connect(self._on_agent_opened)
            ctl.open_failed.connect(self._on_agent_failed)
            ctl.event.connect(self._handle_event)
            ctl.finished.connect(self._handle_done)
            self._agent_ctl = ctl
        return self._agent_ctl

    def load_card(self, card: Card, *, show_history: bool = False) -> None:
        if self._agent_ctl is not None:
            self._agent_ctl.shutdown()
            self._agent_ctl = None

        self._card = card
        self._agent_ready_flag = False
        self._busy = False
        self._pending_files.clear()
        self._sync_files_chips()
        name = card.title or "ИИ-агент"
        self._title.setText(name)
        self._summary.setText(
            card.summary or "Агент готов. Нажмите «Запустить типовую задачу» или напишите свою."
        )
        self._set_status("Подключаю агента…", "busy")
        self._clear_feed()
        self._rebuild_actions()
        self._set_interactive(False)
        saved = load_session_log(card.id, card.workspace_dir)
        if saved:
            self._restoring = True
            try:
                for kind, text in saved:
                    self._append_feed(kind, text)
            finally:
                self._restoring = False
        else:
            self._append_feed(
                "system",
                f"Агент «{name}» готов к работе. Напишите задачу или запустите типовой сценарий.",
            )
        self._ensure_agent_ctl().open_card(card)
        if show_history:
            QTimer.singleShot(300, self.show_session_history)

    def _default_task_prompt(self) -> str:
        if self._card is None:
            return "Выполни типовую задачу по регламенту."
        if self._card.ui_spec.actions:
            return self._card.ui_spec.actions[0].prompt
        title = self._card.title or "агент"
        return (
            f"Выполни рабочую задачу агента «{title}» по инструкции из регламента. "
            "Покажи понятный результат."
        )

    def _run_default_task(self) -> None:
        if self._busy or not self._agent_ready_flag or self._agent_ctl is None:
            return
        prompt = self._default_task_prompt()
        self._input.setPlainText(prompt)
        self._resize_input()
        self._send_chat()

    def _set_status(self, text: str, variant: str) -> None:
        self._status.setText(text)
        self._status.set_variant(variant)

    def _set_interactive(self, enabled: bool) -> None:
        can_use = enabled and not self._busy
        for btn in self._action_buttons:
            btn.setEnabled(can_use)
        self._send_btn.setEnabled(can_use)
        self._attach_btn.setEnabled(can_use)
        self._quick_btn.setEnabled(can_use)
        self._input.setEnabled(can_use)
        self._stop_btn.setEnabled(self._busy)
        if can_use:
            self._input.setPlaceholderText("Например: выполни типовую задачу по регламенту…")
            self._set_status("Готов к работе", "success")
        elif self._busy:
            self._set_status("Агент работает…", "busy")
            self._attach_btn.setEnabled(False)
        elif not self._agent_ready_flag:
            self._input.setPlaceholderText("Подключаю агента…")
            self._set_status("Подключаю агента…", "busy")

    def _pick_files(self) -> None:
        if not self._attach_btn.isEnabled():
            return
        paths, _filter = QFileDialog.getOpenFileNames(
            self,
            "Прикрепить файлы",
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
            if file_path.suffix.lower() not in _ATTACH_SUFFIXES:
                skipped.append(file_path.name)
                continue
            value = str(file_path)
            if value not in self._pending_files:
                self._pending_files.append(value)
                added += 1
        self._sync_files_chips()
        if skipped:
            QMessageBox.information(
                self,
                "Файлы",
                "Поддерживаются: doc, docx, pdf, md, txt, xlsx.\n"
                f"Пропущены: {', '.join(skipped)}",
            )
        elif added == 0 and paths:
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
                self._file_chip(
                    Path(path).name,
                    removable=True,
                    on_remove=lambda p=path: self._remove_pending_file(p),
                )
            )
        self._files_row.addStretch(1)
        self._files_host.show()
        self._resize_input()

    def _file_chip(
        self,
        name: str,
        *,
        removable: bool = False,
        on_remove=None,
    ) -> QFrame:
        chip = QFrame()
        chip.setObjectName("FileChip")
        chip.setStyleSheet(_FILE_CHIP)
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
        if getattr(self, "_resizing_input", False):
            return
        self._resizing_input = True
        try:
            metrics = self._input.fontMetrics()
            line_h = max(metrics.lineSpacing(), metrics.height())
            pad = 16
            min_h = line_h + pad
            max_h = line_h * _INPUT_MAX_LINES + pad
            doc = self._input.document()
            doc.setTextWidth(max(self._input.viewport().width(), 40))
            needed = int(doc.size().height()) + pad
            height = max(min_h, min(max_h, needed))
            if self._input.height() != height:
                self._input.setFixedHeight(height)
            at_max = needed > max_h
            self._input.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAsNeeded if at_max else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
        finally:
            self._resizing_input = False

    def _stop_agent(self) -> None:
        if not self._busy or self._agent_ctl is None:
            return
        self._set_status("Останавливаю…", "warning")
        self._stop_btn.setEnabled(False)
        self._agent_ctl.cancel()

    def _on_agent_opened(self, card_id: str, agent_id: str) -> None:
        self._agent_ready_flag = True
        self._set_interactive(True)
        self._set_status("Готов к работе", "success")
        if self._card and agent_id:
            self._card.cursor_agent_id = agent_id
            self.agent_ready.emit(card_id, agent_id)

    def _on_agent_failed(self, message: str) -> None:
        self._append_feed("error", message)
        self._set_status("Ошибка подключения", "danger")
        self._set_interactive(False)

    def _rebuild_actions(self) -> None:
        self._action_buttons.clear()
        while self._actions_host.count():
            item = self._actions_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                nested = item.layout()
                while nested.count():
                    nested_item = nested.takeAt(0)
                    if nested_item.widget():
                        nested_item.widget().deleteLater()
        if self._card is None:
            return
        for action in self._card.ui_spec.actions:
            btn = QPushButton(action.label)
            btn.setEnabled(False)
            btn.setToolTip(action.hint or action.prompt)
            btn.setFont(app_font(12, QFont.Weight.DemiBold))
            btn.setStyleSheet(secondary_button_qss(radius=10))
            btn.clicked.connect(lambda _=False, p=action.prompt: self._run_action(p))
            self._action_buttons.append(btn)
            self._actions_host.addWidget(btn)
        self._actions_host.addStretch(1)

    def _run_action(self, prompt: str) -> None:
        if self._busy or not self._agent_ready_flag or self._agent_ctl is None:
            return
        self._append_feed("user", prompt)
        self._busy = True
        self._set_status("Агент работает…", "busy")
        self._set_interactive(False)
        self._agent_ctl.send(prompt, action=True)

    def _send_chat(self) -> None:
        if self._busy or not self._agent_ready_flag or self._agent_ctl is None or self._card is None:
            return
        text = self._input.toPlainText().strip()
        files = list(self._pending_files)
        if not text and not files:
            return
        self._input.clear()
        self._resize_input()
        self._pending_files.clear()
        self._sync_files_chips()
        staged = stage_attachments(files, self._card.workspace_dir) if files else []
        display = text
        if staged:
            names = ", ".join(Path(path).name for path in staged)
            attach_line = f"📎 {names}"
            display = f"{text}\n{attach_line}" if text else attach_line
        self._append_feed("user", display)
        self._busy = True
        self._set_status("Агент работает…", "busy")
        self._set_interactive(False)
        self._agent_ctl.send(text, action=False, attachments=staged)

    def _reset_live_blocks(self) -> None:
        self._live_assistant = None
        self._live_thinking = None
        self._last_agent_text = ""
        self._last_thinking_text = ""

    def _handle_event(self, event: object) -> None:
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
                self._update_session_log("agent", merged)
                self._scroll_bottom()
                return
            self._append_feed("agent", merged, live=True)
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
                self._update_session_log("thinking", merged)
                self._scroll_bottom()
                return
            self._append_feed("thinking", merged, live=True, title="Размышление")
        elif et == "tool":
            self._reset_live_blocks()
            name = str(event.get("name") or "")
            status = str(event.get("status") or "")
            result = event.get("result")
            body = format_tool_event(name, status, result)
            self._append_feed("tool", body, title=tool_header_title(name, status))
            for path in paths_from_result(result):
                self._append_file(path)
        elif et == "status":
            text = str(event.get("text") or "")
            if should_show_status(text):
                self._set_status(text or "Агент работает…", "busy")
            return
        elif et == "error":
            self._reset_live_blocks()
            self._append_feed("error", str(event.get("message") or ""))

    def _handle_done(self, payload: object) -> None:
        last_agent = self._last_agent_text
        self._reset_live_blocks()
        self._busy = False
        if self._agent_ready_flag:
            self._set_interactive(True)
            self._set_status("Готов к работе", "success")
        if not isinstance(payload, dict):
            return
        if payload.get("ok"):
            text = str(payload.get("text") or "").strip()
            if not text:
                return
            if text in last_agent or last_agent in text:
                if self._feed_items and self._feed_items[-1].kind == "agent":
                    current = self._feed_items[-1].body_text()
                    if len(text) > len(current):
                        self._feed_items[-1].set_body_text(text)
                        self._update_session_log("agent", text)
                return
            self._append_feed("agent", text)
        elif payload.get("cancelled"):
            self._append_feed("system", "Работа агента остановлена.")
        else:
            msg = str(payload.get("error") or "Ошибка")
            self._append_feed("error", msg)
            self._set_status("Ошибка", "danger")

    def _update_session_log(self, kind: str, text: str) -> None:
        cleaned = (text or "").strip()
        if not cleaned:
            return
        if self._session_log and self._session_log[-1][0] == kind:
            self._session_log[-1] = (kind, cleaned)
        else:
            self._session_log.append((kind, cleaned))
        if not self._restoring:
            self._persist_timer.start()

    def _flush_session_log(self) -> None:
        self._persist_timer.stop()
        if self._restoring or self._card is None:
            return
        save_session_log(self._card.id, self._session_log, self._card.workspace_dir)

    def _append_feed(
        self,
        kind: str,
        text: str,
        title: str = "",
        *,
        live: bool = False,
    ) -> None:
        if kind == "user":
            self._reset_live_blocks()
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
        self._update_session_log(kind, cleaned or text)
        QTimer.singleShot(50, self._scroll_bottom)

    def _append_file(self, path) -> None:
        card = ResultFileCard(path)
        count = self._feed_layout.count()
        self._feed_layout.insertWidget(max(0, count - 1), card)
        QTimer.singleShot(50, self._scroll_bottom)

    def _scroll_bottom(self) -> None:
        bar = self._feed_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear_feed(self) -> None:
        self._feed_items.clear()
        self._session_log.clear()
        self._reset_live_blocks()
        while self._feed_layout.count() > 1:
            item = self._feed_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _on_back(self) -> None:
        self._flush_session_log()
        if self._agent_ctl is not None:
            self._agent_ctl.shutdown()
            self._agent_ctl = None
        clear_confirm_bridge()
        self.back_requested.emit()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._flush_session_log()
        if self._agent_ctl is not None:
            self._agent_ctl.shutdown()
            self._agent_ctl = None
        clear_confirm_bridge()
        super().closeEvent(event)
