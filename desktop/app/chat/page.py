from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, BoardAgent, UserProfile
from app.chat.agent_share import agent_share_payload
from app.chat.api import ChatApi, guess_mime
from app.chat.icons import agent_icon, agent_icon_size, paperclip_icon, paperclip_icon_size
from app.chat.models import ChatAttachment, ChatMessage, ChatThread
from app.chat.crypto import decrypt_text, encrypt_text
from app.chat.store import load_history, save_history
from app.chat.support_agent import echo_command
from app.chat.widgets.agent_picker import AgentPickerDialog
from app.chat.widgets.file_chip import FileChip, FlowLayout
from app.chat.widgets.message_bubble import MessageBubble
from app.chat.widgets.thread_card import ThreadCard
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss

_VIRTUAL_SUPPORT = "support"
_SHELVES = (("queue", "Не назначенные"), ("mine", "Мои"), ("all", "Все"))
_SEND_TIMEOUT_MS = 20_000
_WELCOME = (
    "Здравствуйте! Я агент поддержки turbobot. "
    "Напишите вопрос — помогу с конструктором и агентами."
)


class ChatComposer(QPlainTextEdit):
    send_requested = Signal()
    height_adjusted = Signal()

    _MIN_LINES = 1
    _MAX_LINES = 10
    _PAD = 16

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Сообщение…  Enter — отправить, Shift+Enter — новая строка")
        self.setFont(app_font(13))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QPlainTextEdit { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.12);"
            " border-radius: 12px; padding: 8px; color: #101817; }"
        )
        self.textChanged.connect(self._adjust_height)
        self.document().documentLayout().documentSizeChanged.connect(self._adjust_height)
        self._adjust_height()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._adjust_height()

    def _visual_line_count(self) -> int:
        count = 0
        block = self.document().firstBlock()
        while block.isValid():
            layout = block.layout()
            lines = layout.lineCount() if layout is not None else 0
            count += lines if lines > 0 else 1
            block = block.next()
        return max(1, count)

    def _adjust_height(self, *_args) -> None:
        line_h = max(self.fontMetrics().lineSpacing(), self.fontMetrics().height())
        extra = self._PAD + 2 * self.frameWidth()
        visual = self._visual_line_count()
        lines = min(self._MAX_LINES, max(self._MIN_LINES, visual))
        target = lines * line_h + extra
        if self.height() != target:
            self.setFixedHeight(target)
            self.height_adjusted.emit()
        overflowing = visual > self._MAX_LINES
        policy = (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if overflowing
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        if self.verticalScrollBarPolicy() != policy:
            self.setVerticalScrollBarPolicy(policy)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter}:
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)
                return
            event.accept()
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


def _support_thread(preview: str = "", last_message_at: str = "") -> ChatThread:
    return ChatThread(
        id=_VIRTUAL_SUPPORT,
        kind="support",
        title="Поддержка",
        position="Агент поддержки",
        preview=preview or "Нет сообщений",
        last_message_at=last_message_at,
        pinned=True,
        activity_status="online",
        online=True,
    )


class ChatPage(QWidget):
    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._client = api
        self._api = ChatApi(api)
        self._user: UserProfile | None = None
        self._threads: list[ChatThread] = []
        self._current: str = ""
        self._pending: dict[str, ChatMessage] = {}
        self._bubbles: dict[str, MessageBubble] = {}
        self._pending_files: list[str] = []
        self._local: dict[str, list[ChatMessage]] = {}
        self._api_chat = True
        self._stick_bottom = True

        title = QLabel("Чат")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setContentsMargins(0, 0, 320, 0)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по словам…")
        self._search.setFont(app_font(13))
        self._search.setFixedHeight(36)
        self._search.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.12);"
            " border-radius: 12px; padding: 0 12px; color: #101817; }"
        )
        self._search.textChanged.connect(self._reload_threads)

        self._new_btn = QPushButton("Новый чат")
        self._new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._new_btn.setFixedHeight(36)
        self._new_btn.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
            " border-radius: 12px; }"
        )
        self._new_btn.clicked.connect(self._open_new)

        section = QLabel("Чаты")
        section.setFont(app_font(12, QFont.Weight.DemiBold))
        section.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._list = QListWidget()
        self._list.setSpacing(2)
        self._list.setStyleSheet(
            """
            QListWidget {
                border: none;
                background: transparent;
                outline: none;
            }
            QListWidget::item {
                border: none;
                padding: 0 0 8px 0;
            }
            QListWidget::item:selected { background: transparent; }
            QListWidget::item:hover { background: transparent; }
            """
        )
        self._list.currentRowChanged.connect(self._on_row)

        self._shelf = QComboBox()
        for value, label in _SHELVES:
            self._shelf.addItem(label, value)
        self._shelf.currentIndexChanged.connect(self._reload_support)
        self._support_caption = QLabel("Поддержка")
        self._support_caption.setFont(app_font(12, QFont.Weight.DemiBold))
        self._support_box = QListWidget()
        self._support_box.setMaximumHeight(160)
        self._support_box.itemClicked.connect(self._open_support_item)
        self._shelf.hide()
        self._support_caption.hide()
        self._support_box.hide()

        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self._search)
        left.addWidget(self._new_btn)
        left.addWidget(section)
        left.addWidget(self._list, 1)
        left.addWidget(self._support_caption)
        left.addWidget(self._shelf)
        left.addWidget(self._support_box)

        self._peer = QLabel("Выберите диалог")
        self._peer.setFont(app_font(16, QFont.Weight.DemiBold))
        self._meta = QLabel("")
        self._meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._feed = QVBoxLayout()
        self._feed.setContentsMargins(8, 8, 8, 8)
        self._feed.addStretch(1)
        inner = QWidget()
        inner.setLayout(self._feed)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(inner)
        self._scroll.setStyleSheet("QScrollArea { border: none; }" + scroll_bar_qss())
        bar = self._scroll.verticalScrollBar()
        bar.valueChanged.connect(self._sync_scroll_state)
        bar.rangeChanged.connect(self._on_scroll_range)

        self._feed_wrap = QWidget()
        wrap = QVBoxLayout(self._feed_wrap)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(self._scroll)
        self._down_btn = QPushButton("↓", self._feed_wrap)
        self._down_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._down_btn.setFixedSize(40, 40)
        self._down_btn.setToolTip("К последнему сообщению")
        self._down_btn.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
            " border-radius: 20px; font-size: 18px; }"
        )
        self._down_btn.clicked.connect(lambda: self._scroll_to_bottom(force=True))
        self._down_btn.hide()

        self._input = ChatComposer()
        self._input.send_requested.connect(self._send)
        self._input.height_adjusted.connect(self._place_down_btn)
        self._attach = QPushButton()
        self._attach.setCursor(Qt.CursorShape.PointingHandCursor)
        self._attach.setToolTip("Прикрепить файл")
        self._attach.setFixedSize(36, 36)
        self._attach.setIcon(paperclip_icon(22))
        self._attach.setIconSize(paperclip_icon_size(22))
        self._attach.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 10px; }"
            "QPushButton:hover { background: rgba(8,116,95,0.10); }"
            "QPushButton:pressed { background: rgba(8,116,95,0.18); }"
        )
        self._attach.clicked.connect(self._pick_file)
        self._agent_btn = QPushButton()
        self._agent_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._agent_btn.setToolTip("Отправить агента")
        self._agent_btn.setFixedSize(36, 36)
        self._agent_btn.setIcon(agent_icon(22))
        self._agent_btn.setIconSize(agent_icon_size(22))
        self._agent_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 10px; }"
            "QPushButton:hover { background: rgba(8,116,95,0.10); }"
            "QPushButton:pressed { background: rgba(8,116,95,0.18); }"
        )
        self._agent_btn.clicked.connect(self._pick_agent)
        self._send_btn = QPushButton("Отправить")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFixedHeight(36)
        self._send_btn.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
            " border-radius: 12px; padding: 0 16px; }"
        )
        self._send_btn.clicked.connect(lambda: self._send())
        self._files_host = QWidget()
        self._files_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._files_layout = FlowLayout(self._files_host, spacing=8)
        self._files_host.hide()
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.addSpacing(80)
        chips.addWidget(self._files_host, 1)
        composer = QHBoxLayout()
        composer.addWidget(self._attach, 0, Qt.AlignmentFlag.AlignBottom)
        composer.addWidget(self._agent_btn, 0, Qt.AlignmentFlag.AlignBottom)
        composer.addWidget(self._input, 1)
        composer.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignBottom)
        compose_col = QVBoxLayout()
        compose_col.setSpacing(8)
        compose_col.addLayout(chips)
        compose_col.addLayout(composer)

        right = QVBoxLayout()
        right.addWidget(self._peer)
        right.addWidget(self._meta)
        right.addWidget(self._feed_wrap, 1)
        right.addLayout(compose_col)

        body = QHBoxLayout()
        body.setSpacing(14)
        left_wrap = QWidget()
        left_wrap.setFixedWidth(320)
        left_wrap.setLayout(left)
        right_wrap = QWidget()
        right_wrap.setLayout(right)
        body.addWidget(left_wrap, 0)
        body.addWidget(right_wrap, 1)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(title)
        root.addLayout(body, 1)

    def set_user(self, user: UserProfile | None) -> None:
        previous = self._user.id if self._user is not None else ""
        self._user = user
        support = bool(user and user.is_support)
        self._support_box.setVisible(support)
        self._support_caption.setVisible(support)
        self._shelf.setVisible(support)
        if user is not None and user.id != previous:
            self._local = load_history(user.id)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_down_btn()

    def refresh(self) -> None:
        self._reload_threads()
        if not self._current:
            self._open_thread(_VIRTUAL_SUPPORT)
            self._select_thread(_VIRTUAL_SUPPORT)
        if self._user and self._user.is_support:
            self._reload_support()

    def apply_event(self, payload: dict) -> None:
        kind = str(payload.get("type") or "")
        thread_id = str(payload.get("thread_id") or "")
        if kind == "chat_message":
            message = payload.get("message") or {}
            if isinstance(message, dict):
                message["text"] = decrypt_text(str(message.get("text") or ""))
            client_id = str(message.get("client_id") or "")
            pending = self._pending.pop(client_id, None)
            if pending is not None:
                self._set_receipt(client_id, "delivered")
            if thread_id and self._current in {"", _VIRTUAL_SUPPORT}:
                self._current = thread_id
            self._reload_threads()
            if thread_id and thread_id == self._current:
                self._load_messages(self._current, pin_bottom=self._stick_bottom)
            return
        if kind == "thread_opened" and thread_id:
            self._current = thread_id
            self._reload_threads()
            self._select_thread(thread_id)
            self._load_messages(thread_id, pin_bottom=True)
            return
        if kind in {"chat_receipt", "ticket_updated", "presence"}:
            self._reload_threads()
            if self._current and self._current != _VIRTUAL_SUPPORT:
                self._load_messages(self._current, pin_bottom=self._stick_bottom)
            if kind == "ticket_updated" and self._user and self._user.is_support:
                self._reload_support()

    def _reload_threads(self) -> None:
        needle = self._search.text().strip().casefold()
        remote: list[ChatThread] = []
        self._api_chat = True
        try:
            remote = [
                item
                for item in self._api.threads(self._search.text().strip())
                if item.id != _VIRTUAL_SUPPORT
            ]
        except ApiError:
            self._api_chat = False
            remote = []
        local_rows = self._local.get(_VIRTUAL_SUPPORT) or []
        last = local_rows[-1] if local_rows else None
        preview = ""
        if last:
            preview = last.text.strip()
            if not preview and last.agent:
                preview = f"Агент: {last.agent.get('title') or 'ИИ-агент'}"
            if not preview and last.attachments:
                preview = last.attachments[0].filename
        support = _support_thread(preview, last.created_at if last else "")
        hay = " ".join([support.title, support.position, support.preview]).casefold()
        self._threads = ([support] if not needle or needle in hay else []) + remote
        current = self._current or _VIRTUAL_SUPPORT
        self._list.blockSignals(True)
        self._list.clear()
        selected = -1
        for index, thread in enumerate(self._threads):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, thread.id)
            card = ThreadCard(thread, selected=thread.id == current)
            item.setSizeHint(QSize(300, 86))
            self._list.addItem(item)
            self._list.setItemWidget(item, card)
            if thread.id == current:
                selected = index
        if selected >= 0:
            self._list.setCurrentRow(selected)
        elif self._list.count() and current == _VIRTUAL_SUPPORT:
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)

    def _reload_support(self) -> None:
        if self._user is None or not self._user.is_support:
            return
        shelf = str(self._shelf.currentData() or "queue")
        self._support_box.clear()
        try:
            rows = self._api.support_shelf(shelf)
        except ApiError:
            rows = []
        for row in rows:
            item = QListWidgetItem(f"{row.get('author_fio')} · {row.get('preview') or 'обращение'}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._support_box.addItem(item)

    def _on_row(self, row: int) -> None:
        if row < 0 or row >= self._list.count():
            return
        thread_id = str(self._list.item(row).data(Qt.ItemDataRole.UserRole) or "")
        self._open_thread(thread_id)

    def _open_support_item(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole) or {}
        thread_id = str(data.get("thread_id") or "")
        ticket_id = str(data.get("id") or "")
        if ticket_id and str(self._shelf.currentData() or "") == "queue":
            try:
                self._api.command({"type": "ticket_assign", "ticket_id": ticket_id})
            except ApiError:
                pass
        if thread_id:
            self._open_thread(thread_id)

    def _select_thread(self, thread_id: str) -> None:
        for index in range(self._list.count()):
            if str(self._list.item(index).data(Qt.ItemDataRole.UserRole) or "") == thread_id:
                self._list.blockSignals(True)
                self._list.setCurrentRow(index)
                self._list.blockSignals(False)
                break

    def _open_thread(self, thread_id: str) -> None:
        self._current = thread_id
        thread = next((item for item in self._threads if item.id == thread_id), None)
        if thread_id == _VIRTUAL_SUPPORT and thread is None:
            thread = _support_thread()
        self._peer.setText(thread.title if thread else "Диалог")
        if thread_id == _VIRTUAL_SUPPORT:
            self._meta.setText("Агент поддержки · в сети")
        else:
            labels = []
            if thread:
                labels = [thread.position]
                if thread.online:
                    labels.append("в сети")
                labels.append({"busy": "занят", "away": "не активен"}.get(thread.activity_status, ""))
            self._meta.setText(" · ".join(part for part in labels if part))
        if thread_id == _VIRTUAL_SUPPORT:
            self._stick_bottom = True
            self._ensure_support_welcome()
            self._render_local_or_remote(thread_id)
            return
        if thread_id:
            self._stick_bottom = True
            self._load_messages(thread_id, pin_bottom=True)
            try:
                self._api.command({"type": "mark_read", "thread_id": thread_id})
            except ApiError:
                pass
        else:
            self._clear_feed()

    def _clear_feed(self) -> None:
        while self._feed.count() > 1:
            item = self._feed.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _ensure_support_welcome(self) -> None:
        rows = self._local.setdefault(_VIRTUAL_SUPPORT, [])
        if rows:
            return
        rows.append(
            ChatMessage(
                id="welcome",
                thread_id=_VIRTUAL_SUPPORT,
                sender_id="support-agent",
                mine=False,
                text=_WELCOME,
                created_at=datetime.now(timezone.utc).isoformat(),
                receipt="received",
            )
        )
        self._persist()

    def _at_bottom(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        return bar.value() >= max(0, bar.maximum() - 32)

    def _place_down_btn(self) -> None:
        if not hasattr(self, "_down_btn"):
            return
        area = self._feed_wrap.rect()
        self._down_btn.move(max(8, area.width() - 52), max(8, area.height() - 52))
        self._down_btn.raise_()

    def _sync_scroll_state(self) -> None:
        self._stick_bottom = self._at_bottom()
        self._down_btn.setVisible(not self._stick_bottom)
        self._place_down_btn()

    def _on_scroll_range(self, *_args) -> None:
        if self._stick_bottom:
            self._scroll_to_bottom(force=True)
        else:
            self._down_btn.setVisible(True)
            self._place_down_btn()

    def _scroll_to_bottom(self, *, force: bool = False) -> None:
        if not force and not self._stick_bottom:
            self._down_btn.setVisible(True)
            self._place_down_btn()
            return
        self._stick_bottom = True
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._down_btn.hide()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        QTimer.singleShot(80, lambda: bar.setValue(bar.maximum()))

    def _render_rows(self, rows: list[ChatMessage], *, pin_bottom: bool = True) -> None:
        self._clear_feed()
        for message in rows:
            pending = self._pending.get(message.client_id)
            if pending is not None and pending.receipt == "failed":
                message.receipt = "failed"
            bubble = MessageBubble(message)
            if message.client_id:
                self._bubbles[message.client_id] = bubble
            self._feed.insertWidget(self._feed.count() - 1, bubble)
        if pin_bottom:
            self._scroll_to_bottom(force=True)

    def _render_local_or_remote(self, thread_id: str) -> None:
        if self._api_chat and thread_id != _VIRTUAL_SUPPORT:
            self._load_messages(thread_id, pin_bottom=True)
            return
        if self._api_chat:
            try:
                rows = self._api.messages(thread_id)
                if rows:
                    self._render_rows(rows, pin_bottom=True)
                    return
            except ApiError:
                self._api_chat = False
        self._render_rows(list(self._local.get(thread_id) or []), pin_bottom=True)

    def _load_messages(self, thread_id: str, *, pin_bottom: bool = True) -> None:
        try:
            rows = self._api.messages(thread_id)
        except ApiError:
            rows = list(self._local.get(thread_id) or [])
        self._render_rows(rows, pin_bottom=pin_bottom)

    def _persist(self) -> None:
        if self._user is None:
            return
        save_history(self._user.id, self._local)

    def _store_local(self, message: ChatMessage) -> None:
        self._local.setdefault(message.thread_id or _VIRTUAL_SUPPORT, []).append(message)
        self._persist()

    def _open_new(self) -> None:
        try:
            users = self._api.directory()
        except ApiError as exc:
            self._peer.setText(str(exc))
            return
        peers = [user for user in users if self._user is None or user.id != self._user.id]
        labels = [f"{user.fio} · {user.position}" for user in peers]
        if not labels:
            return
        choice, ok = QInputDialog.getItem(self, "Новый чат", "Сотрудник", labels, 0, False)
        if not ok:
            return
        peer = peers[labels.index(choice)]
        try:
            self._api.command({"type": "open_dm", "peer_id": peer.id})
        except ApiError:
            return
        QTimer.singleShot(400, self.refresh)

    def _list_shareable_agents(self) -> list[BoardAgent]:
        try:
            board = self._client.get_workflow_board()
            agents = [item for item in board.agents if item.kind == "workflow"]
            if agents:
                return agents
        except ApiError:
            pass
        items = self._client.list_workflows()
        return [
            BoardAgent(id=item.id, title=item.title, description="", phase=item.phase)
            for item in items
            if (item.phase or "") == "done"
        ]

    def _pick_agent(self) -> None:
        try:
            agents = self._list_shareable_agents()
        except ApiError as exc:
            QMessageBox.warning(self, "Агенты", exc.message or "Не удалось загрузить агентов")
            return
        if not agents:
            QMessageBox.information(self, "Агенты", "Нет опубликованных агентов для отправки.")
            return
        dialog = AgentPickerDialog(agents, self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.chosen is None:
            return
        record = None
        try:
            record = self._client.get_workflow(dialog.chosen.id)
        except ApiError:
            record = None
        self._send(agent=agent_share_payload(dialog.chosen, record), keep_composer=True)

    def _pick_file(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Файлы")
        added = False
        for path in paths:
            if path and path not in self._pending_files:
                self._pending_files.append(path)
                added = True
        if added:
            self._refresh_file_chips()

    def _remove_file(self, path: str) -> None:
        self._pending_files = [item for item in self._pending_files if item != path]
        self._refresh_file_chips()

    def _refresh_file_chips(self) -> None:
        while self._files_layout.count():
            item = self._files_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for path in self._pending_files:
            chip = FileChip(path)
            chip.removed.connect(self._remove_file)
            self._files_layout.addWidget(chip)
        self._files_host.setVisible(bool(self._pending_files))
        self._place_down_btn()

    def _describe_files(self, paths: list[str]) -> list[dict]:
        items: list[dict] = []
        for raw in paths:
            path = Path(raw)
            file_id = uuid4().hex
            size = path.stat().st_size if path.is_file() else 0
            items.append(
                {
                    "file_id": file_id,
                    "filename": path.name,
                    "size": size,
                    "mime": guess_mime(path),
                    "uploaded": False,
                }
            )
        return items

    def _send(self, agent: dict | None = None, *, keep_composer: bool = False) -> None:
        text = "" if agent and keep_composer else self._input.toPlainText().strip()
        files = [] if agent and keep_composer else list(self._pending_files)
        if not text and not files and not agent:
            return
        support = self._current in {"", _VIRTUAL_SUPPORT}
        thread_id = _VIRTUAL_SUPPORT if support else self._current
        client_id = uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        attachments_meta = self._describe_files(files)
        file_ids = [str(item["file_id"]) for item in attachments_meta]
        payload = {
            "type": "send_message",
            "client_id": client_id,
            "thread_id": "" if support else thread_id,
            "kind": "support" if support else "",
            "text": encrypt_text(text),
            "file_ids": file_ids,
            "files": attachments_meta,
            "agent": agent,
            "user_id": self._user.id if self._user else "",
            "created_at": created_at,
        }
        optimistic = ChatMessage(
            id=client_id,
            thread_id=thread_id,
            sender_id=self._user.id if self._user else "",
            mine=True,
            text=text,
            client_id=client_id,
            created_at=created_at,
            receipt="sending",
            attachments=[
                ChatAttachment(
                    id=str(item["file_id"]),
                    filename=str(item["filename"]),
                    mime=str(item["mime"]),
                    size=int(item["size"] or 0),
                )
                for item in attachments_meta
            ],
            agent=agent,
        )
        self._pending[client_id] = optimistic
        bubble = MessageBubble(optimistic)
        self._bubbles[client_id] = bubble
        self._feed.insertWidget(self._feed.count() - 1, bubble)
        self._scroll_to_bottom(force=True)
        queued = False
        for path, meta in zip(files, attachments_meta):
            try:
                uploaded = self._api.upload(path)
            except ApiError:
                self._api_chat = False
                continue
            remote_id = str(uploaded.get("file_id") or "")
            if remote_id:
                meta["file_id"] = remote_id
                meta["uploaded"] = True
                meta["filename"] = str(uploaded.get("filename") or meta["filename"])
                meta["mime"] = str(uploaded.get("mime") or meta["mime"])
                meta["size"] = int(uploaded.get("size") or meta["size"])
        payload["file_ids"] = [str(item["file_id"]) for item in attachments_meta]
        payload["files"] = attachments_meta
        try:
            self._api.command(payload)
            queued = True
            QTimer.singleShot(_SEND_TIMEOUT_MS, lambda: self._fail_if_pending(client_id))
        except ApiError:
            self._api_chat = False
            if support:
                self._set_receipt(client_id, "delivered")
                self._pending.pop(client_id, None)
                self._store_local(optimistic)
            else:
                self._set_receipt(client_id, "failed")
        if support:
            self._set_receipt(client_id, "delivered")
            QTimer.singleShot(350, lambda cid=client_id: self._echo_payload(payload, cid))
        elif queued:
            pass
        elif self._current and self._current != _VIRTUAL_SUPPORT:
            self._load_messages(self._current)
        if not keep_composer:
            self._input.clear()
            self._input.setPlaceholderText("Сообщение…  Enter — отправить, Shift+Enter — новая строка")
            self._pending_files.clear()
            self._refresh_file_chips()
        self._reload_threads()

    def _set_receipt(self, client_id: str, status: str) -> None:
        pending = self._pending.get(client_id)
        if pending is not None:
            pending.receipt = status
        bubble = self._bubbles.get(client_id)
        if bubble is not None:
            bubble.set_receipt(status)

    def _echo_payload(self, payload: dict, client_id: str = "") -> None:
        reply = ChatMessage(
            id=uuid4().hex,
            thread_id=_VIRTUAL_SUPPORT,
            sender_id="support-agent",
            mine=False,
            text=echo_command(payload),
            created_at=datetime.now(timezone.utc).isoformat(),
            receipt="received",
        )
        self._store_local(reply)
        if client_id:
            self._set_receipt(client_id, "read")
        if self._current == _VIRTUAL_SUPPORT:
            self._feed.insertWidget(self._feed.count() - 1, MessageBubble(reply))
            self._scroll_to_bottom(force=False)
        self._reload_threads()

    def _fail_if_pending(self, client_id: str) -> None:
        pending = self._pending.get(client_id)
        if pending is None or pending.receipt != "sending":
            return
        self._set_receipt(client_id, "failed")
        if self._current and self._current != _VIRTUAL_SUPPORT:
            self._load_messages(self._current)
