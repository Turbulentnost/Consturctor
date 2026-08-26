from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Thread
from uuid import uuid4

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, BoardAgent, UserProfile
from app.chat.agent_share import agent_share_payload
from app.chat.avatars import load_peer_avatar, peek_avatar
from app.chat.api import ChatApi, guess_mime
from app.chat.icons import agent_icon, agent_icon_size, paperclip_icon, paperclip_icon_size
from app.chat.models import ChatAttachment, ChatMessage, ChatThread, DirectoryUser
from app.chat.crypto import decrypt_text, encrypt_text
from app.chat.shared_bus import append_shared, load_shared, roster_upsert
from app.chat.store import load_dialogs, load_history, save_history
from app.chat.support_agent import echo_command
from app.chat.widgets.agent_offer_dialog import AgentOfferDialog
from app.chat.widgets.agent_picker import AgentPickerDialog
from app.chat.widgets.employee_panel import EmployeePanel
from app.chat.widgets.profile_dialog import ChatProfileDialog
from app.chat.widgets.user_picker import UserPickerDialog
from app.chat.widgets.file_chip import FileChip, FlowLayout
from app.chat.wallpaper import CHAT_BG_GRID, CHAT_FRAME_RADIUS, ChatFrameRing, ChatWallpaper
from app.chat.widgets.message_bubble import MessageBubble
from app.chat.widgets.thread_card import ThreadCard
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, circular_pixmap, scroll_bar_qss

_CHAT_PANE_QSS = """
QFrame#ChatListPane, QFrame#ChatPane {
    background: #FFFFFF;
    border: 1px solid rgba(16, 24, 23, 0.10);
    border-radius: 18px;
}
"""

_VIRTUAL_SUPPORT = "support"
_SHELVES = (("queue", "Не назначенные"), ("mine", "Мои"), ("all", "Все"))
_SEND_TIMEOUT_MS = 20_000
_CHAT_SURFACE_MAX_WIDTH = 860
_WELCOME = (
    "Здравствуйте! Я агент поддержки turbobot. "
    "Напишите вопрос — помогу с конструктором и агентами."
)


class ChatComposer(QPlainTextEdit):
    send_requested = Signal()
    height_adjusted = Signal()

    _MIN_LINES = 1
    _MAX_LINES = 10
    _PAD = 14

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Напишите сообщение...")
        self.setFont(app_font(13))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none;"
            " padding: 7px 8px; color: #101817; }"
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


def _stamp(value: str) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _later_stamp(*values: str) -> str:
    best = ""
    best_ts = float("-inf")
    for value in values:
        ts = _stamp(value)
        if ts > best_ts:
            best_ts = ts
            best = value
    return best


def sort_threads(threads: list[ChatThread]) -> list[ChatThread]:
    pinned = [item for item in threads if item.pinned]
    rest = [item for item in threads if not item.pinned]
    pinned.sort(key=lambda item: _stamp(item.last_message_at), reverse=True)
    rest.sort(key=lambda item: _stamp(item.last_message_at), reverse=True)
    return pinned + rest


def peer_key(thread: ChatThread) -> str:
    title = (thread.title or "").strip().casefold()
    if title:
        return f"fio:{title}"
    peer = (thread.peer_id or thread.id or "").strip()
    return f"id:{peer.casefold()}"


def thread_matches(current: str, thread_id: str, peer_id: str = "") -> bool:
    if not current:
        return False
    if thread_id and current == thread_id:
        return True
    return bool(peer_id) and current == peer_id


def dedupe_dm_threads(threads: list[ChatThread]) -> list[ChatThread]:
    best: dict[str, ChatThread] = {}
    order: list[str] = []
    for thread in threads:
        key = peer_key(thread)
        prev = best.get(key)
        if prev is None:
            best[key] = thread
            order.append(key)
            continue
        prev_ts = prev.last_message_at or ""
        next_ts = thread.last_message_at or ""
        if next_ts > prev_ts:
            best[key] = thread
        elif next_ts == prev_ts and thread.peer_id and not prev.peer_id:
            best[key] = thread
    return [best[key] for key in order]


def preview_of(message: ChatMessage | None) -> str:
    if message is None:
        return ""
    text = (message.text or "").strip()
    if text:
        return text
    if message.agent:
        return f"Агент: {message.agent.get('title') or 'ИИ-агент'}"
    if message.attachments:
        return message.attachments[0].filename
    return ""


def _message_day(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().date().isoformat()
    except ValueError:
        return value[:10] if len(value) >= 10 else ""


def _date_label(value: str) -> str:
    if not value:
        return ""
    try:
        day = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().date()
    except ValueError:
        return value[:10] if len(value) >= 10 else value
    today = datetime.now().astimezone().date()
    if day == today:
        return "Сегодня"
    if (today - day).days == 1:
        return "Вчера"
    return day.strftime("%d.%m.%Y")


class DateSeparator(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(app_font(10, QFont.Weight.Medium))
        self.setStyleSheet(
            "QLabel { background: rgba(255,255,255,0.78); color: #6B7773;"
            " border-radius: 12px; padding: 4px 12px; }"
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)


def _support_thread(preview: str = "", last_message_at: str = "") -> ChatThread:
    return ChatThread(
        id=_VIRTUAL_SUPPORT,
        kind="support",
        title="Поддержка",
        position="Агент поддержки",
        preview=preview or "Нет сообщений",
        last_message_at=last_message_at,
        pinned=False,
        activity_status="online",
        online=True,
    )


class ChatPage(QWidget):
    open_agent_requested = Signal(str, str)
    threads_changed = Signal()
    _avatar_ready = Signal(str, object)

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
        self._local_threads: dict[str, ChatThread] = {}
        self._api_chat = True
        self._stick_bottom = True
        self._shared_stamp = ""
        self._fresh_ids: set[str] = set()
        self._opening = False
        self._aliases: dict[str, str] = {}
        self._avatar_peer_id = ""
        self._remote_cache: list[ChatThread] = []
        self._rendered_keys: list[str] = []
        self._rendered_day = ""
        self._pending_remote_thread = ""
        self._poll = QTimer(self)
        self._poll.setInterval(800)
        self._poll.timeout.connect(self._poll_shared)
        self._poll.start()
        self._avatar_ready.connect(self._on_avatar_ready)

        title = QLabel("Чат")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        title.setContentsMargins(0, 0, 0, 0)

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
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
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

        self._avatar = QLabel("?")
        self._avatar.setFixedSize(40, 40)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setFont(app_font(14, QFont.Weight.DemiBold))
        self._avatar.setStyleSheet(
            "background: #08745F; color: #FFFFFF; border-radius: 20px;"
        )
        self._avatar.setCursor(Qt.CursorShape.PointingHandCursor)
        self._peer = QLabel("Выберите диалог")
        self._peer.setFont(app_font(16, QFont.Weight.DemiBold))
        self._peer.setCursor(Qt.CursorShape.PointingHandCursor)
        self._meta = QLabel("Нажмите, чтобы открыть профиль")
        self._meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._meta.setCursor(Qt.CursorShape.PointingHandCursor)
        identity = QWidget()
        identity.setCursor(Qt.CursorShape.PointingHandCursor)
        identity_col = QVBoxLayout(identity)
        identity_col.setContentsMargins(0, 0, 0, 0)
        identity_col.setSpacing(0)
        identity_col.addWidget(self._peer)
        identity_col.addWidget(self._meta)
        self._avatar.mousePressEvent = lambda event: self._open_profile()  # type: ignore[method-assign]
        identity.mousePressEvent = lambda event: self._open_profile()  # type: ignore[method-assign]
        self._pin_btn = QPushButton("Закрепить")
        self._pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_btn.setFixedHeight(32)
        self._pin_btn.setMinimumWidth(112)
        self._pin_btn.setCheckable(True)
        self._pin_btn.hide()
        self._pin_btn.clicked.connect(self._toggle_current_pin)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(self._avatar, 0)
        header.addWidget(identity, 1)
        header.addWidget(self._pin_btn, 0, Qt.AlignmentFlag.AlignTop)

        self._feed = QVBoxLayout()
        self._feed.setContentsMargins(12, 12, 12, 12)
        self._feed.addStretch(1)
        self._feed_host = QWidget()
        self._feed_host.setMinimumWidth(640)
        self._feed_host.setMaximumWidth(_CHAT_SURFACE_MAX_WIDTH)
        self._feed_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._feed_host.setStyleSheet("background: transparent;")
        self._feed_host.setAutoFillBackground(False)
        self._feed_host.setLayout(self._feed)
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        inner.setAutoFillBackground(False)
        inner_layout = QHBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        inner_layout.setSpacing(0)
        inner_layout.addStretch(1)
        inner_layout.addWidget(self._feed_host, 1)
        inner_layout.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidget(inner)
        self._scroll.setStyleSheet(
            "QScrollArea { border: none; background: transparent; }"
            "QScrollArea > QWidget { background: transparent; }"
            + scroll_bar_qss()
        )
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.viewport().setStyleSheet("background: transparent;")
        bar = self._scroll.verticalScrollBar()
        bar.valueChanged.connect(self._sync_scroll_state)
        bar.rangeChanged.connect(self._on_scroll_range)

        self._feed_wrap = QWidget()
        self._feed_wrap.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._feed_wrap.setStyleSheet("background: transparent;")
        self._wallpaper = ChatWallpaper(self._feed_wrap, CHAT_BG_GRID, CHAT_FRAME_RADIUS)
        self._frame_ring = ChatFrameRing(self._feed_wrap, CHAT_FRAME_RADIUS)
        stack = QStackedLayout(self._feed_wrap)
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.addWidget(self._wallpaper)
        stack.addWidget(self._scroll)
        stack.addWidget(self._frame_ring)
        stack.setCurrentWidget(self._scroll)
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
        self._agent_btn.setToolTip("Связать с агентом")
        self._agent_btn.setText("Связать с агентом")
        self._agent_btn.setFixedHeight(36)
        self._agent_btn.setIcon(agent_icon(16))
        self._agent_btn.setIconSize(agent_icon_size(16))
        self._agent_btn.setStyleSheet(
            "QPushButton { background: #F3FAF7; color: #08745F; border: none;"
            " border-radius: 12px; padding: 0 14px; }"
            "QPushButton:hover { background: #EAF7F3; }"
        )
        self._agent_btn.clicked.connect(self._pick_agent)
        self._send_btn = QPushButton("➤")
        self._send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send_btn.setFixedSize(48, 48)
        self._send_btn.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
            " border-radius: 24px; font-size: 20px; padding-left: 2px; }"
            "QPushButton:hover { background: #0A8670; }"
        )
        self._send_btn.clicked.connect(lambda: self._send())
        self._files_host = QWidget()
        self._files_host.setMinimumWidth(640)
        self._files_host.setMaximumWidth(_CHAT_SURFACE_MAX_WIDTH)
        self._files_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._files_layout = FlowLayout(self._files_host, spacing=8)
        self._files_host.hide()
        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.addStretch(1)
        chips.addWidget(self._files_host, 1)
        chips.addStretch(1)
        composer_box = QFrame()
        composer_box.setObjectName("composerBox")
        composer_box.setMinimumWidth(640)
        composer_box.setMaximumWidth(_CHAT_SURFACE_MAX_WIDTH)
        composer_box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        composer_box.setStyleSheet(
            "QFrame#composerBox { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.10);"
            " border-radius: 18px; }"
        )
        composer = QHBoxLayout(composer_box)
        composer.setContentsMargins(12, 8, 12, 8)
        composer.setSpacing(10)
        composer.addWidget(self._attach, 0, Qt.AlignmentFlag.AlignVCenter)
        composer.addWidget(self._input, 1, Qt.AlignmentFlag.AlignVCenter)
        composer.addWidget(self._agent_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        composer.addWidget(self._send_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        compose_col = QVBoxLayout()
        compose_col.setSpacing(8)
        compose_col.addLayout(chips)
        compose_col.addWidget(composer_box, 0, Qt.AlignmentFlag.AlignHCenter)

        self._info_panel = EmployeePanel()
        self._info_panel.profile_requested.connect(self._open_profile)
        self._info_panel.agent_opened.connect(lambda payload: self._open_agent_card(payload, mine=False))
        self._info_panel.hide()

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet("background: rgba(8, 116, 95, 0.12); border: none;")

        right = QVBoxLayout()
        right.setContentsMargins(14, 12, 14, 12)
        right.setSpacing(10)
        right.addLayout(header)
        right.addWidget(divider)
        right.addWidget(self._feed_wrap, 1)
        right.addLayout(compose_col)

        body = QHBoxLayout()
        body.setSpacing(12)
        left.setContentsMargins(12, 12, 12, 12)
        self._left_wrap = QFrame()
        self._left_wrap.setObjectName("ChatListPane")
        self._left_wrap.setStyleSheet(_CHAT_PANE_QSS)
        self._left_wrap.setFixedWidth(280)
        self._left_wrap.setLayout(left)
        self._left_wrap.hide()
        right_wrap = QFrame()
        right_wrap.setObjectName("ChatPane")
        right_wrap.setStyleSheet(_CHAT_PANE_QSS)
        right_wrap.setLayout(right)
        body.addWidget(self._left_wrap, 0)
        body.addWidget(right_wrap, 1)
        body.addWidget(self._info_panel, 0)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(title)
        root.addLayout(body, 1)

    def current_thread_id(self) -> str:
        return self._current

    def current_peer_id(self) -> str:
        thread = self._current_thread()
        if thread is None:
            return ""
        return thread.peer_id or ("" if thread.id.startswith("thr-") else thread.id)

    def _canon(self, thread_id: str) -> str:
        return self._aliases.get(thread_id, thread_id)

    def _bind_ids(self, server_id: str, peer_id: str) -> None:
        if not server_id:
            return
        self._aliases[server_id] = server_id
        if peer_id and peer_id != server_id:
            self._aliases[peer_id] = server_id
            self._migrate_thread(peer_id, server_id, peer_id)

    def _migrate_thread(self, old_id: str, new_id: str, peer_id: str) -> None:
        if not old_id or not new_id or old_id == new_id:
            return
        old_thread = self._local_threads.pop(old_id, None)
        new_thread = self._local_threads.get(new_id)
        if old_thread is not None and new_thread is None:
            old_thread.id = new_id
            old_thread.peer_id = peer_id or old_thread.peer_id
            self._local_threads[new_id] = old_thread
        elif old_thread is not None and new_thread is not None:
            new_thread.peer_id = peer_id or new_thread.peer_id or old_thread.peer_id
            if old_thread.title:
                new_thread.title = old_thread.title
        old_rows = self._local.pop(old_id, [])
        if old_rows:
            dest = self._local.setdefault(new_id, [])
            seen = {item.id or item.client_id for item in dest}
            for item in old_rows:
                key = item.id or item.client_id
                if key and key in seen:
                    continue
                dest.append(item)
                if key:
                    seen.add(key)
        if self._current == old_id:
            self._current = new_id

    def _peer_for(self, thread_id: str) -> str:
        thread = self._local_threads.get(thread_id) or next(
            (item for item in self._threads if item.id == thread_id),
            None,
        )
        if thread is None:
            return ""
        return thread.peer_id or ""

    def _is_viewing(self, thread_id: str, peer_id: str = "") -> bool:
        current = self._current
        if not current:
            return False
        if self._canon(current) == self._canon(thread_id):
            return True
        return thread_matches(current, thread_id, peer_id)

    def _ingest_remote_message(self, payload: dict) -> ChatMessage | None:
        raw = payload.get("message") or {}
        if not isinstance(raw, dict):
            return None
        thread_id = str(payload.get("thread_id") or raw.get("thread_id") or "")
        sender = str(raw.get("sender_id") or "")
        me = self._user.id if self._user is not None else ""
        members = [str(item) for item in (payload.get("members") or []) if item]
        peer_id = next((item for item in members if item != me), "")
        if not peer_id and sender and sender != me:
            peer_id = sender
        if thread_id:
            self._bind_ids(thread_id, peer_id)
        canon = self._canon(thread_id or peer_id)
        incoming = ChatMessage(
            id=str(raw.get("id") or ""),
            thread_id=canon,
            sender_id=sender,
            mine=bool(me) and sender == me,
            text=decrypt_text(str(raw.get("text") or "")),
            client_id=str(raw.get("client_id") or ""),
            created_at=str(raw.get("created_at") or ""),
            receipt="delivered",
        )
        rows = self._local.setdefault(canon, [])
        if not any(
            (incoming.id and item.id == incoming.id)
            or (incoming.client_id and item.client_id == incoming.client_id)
            for item in rows
        ):
            rows.append(incoming)
        if self._user is not None:
            if peer_id:
                append_shared(self._user.id, peer_id, incoming)
            if canon:
                append_shared(self._user.id, canon, incoming)
        thread = self._local_threads.get(canon)
        if thread is None:
            thread = ChatThread(
                id=canon,
                kind="dm",
                title="",
                peer_id=peer_id,
            )
            self._local_threads[canon] = thread
        if peer_id:
            thread.peer_id = peer_id
        self._apply_activity(thread, [incoming], viewing=self._is_viewing(canon, peer_id))
        self._persist()
        return incoming

    def sidebar_dialogs(self) -> list[ChatThread]:
        result: list[ChatThread] = []
        for thread in list(self._threads) + list(self._local_threads.values()):
            if thread.id == _VIRTUAL_SUPPORT or thread.kind == "support":
                continue
            if not self._dialog_has_messages(thread):
                continue
            result.append(thread)
        return sort_threads(dedupe_dm_threads(result))

    def _dialog_has_messages(self, thread: ChatThread) -> bool:
        keys = [thread.id, thread.peer_id, self._canon(thread.id)]
        rows = []
        for key in keys:
            if key and self._local.get(key):
                rows = self._local[key]
                break
        if self._user is not None:
            for key in keys:
                if not key:
                    continue
                shared = load_shared(self._user.id, key)
                if shared:
                    rows = shared
                    break
        if rows:
            return True
        preview = (thread.preview or "").strip()
        return bool(preview) and preview != "Нет сообщений"

    def open_existing_dialog(self, thread_id: str) -> None:
        if not thread_id:
            return
        thread = self._local_threads.get(thread_id) or next(
            (item for item in self._threads if item.id == thread_id),
            None,
        )
        if thread is not None and thread.peer_id:
            self._bind_ids(thread.id, thread.peer_id)
        self._open_thread(self._canon(thread_id))
        self._select_thread(self._canon(thread_id))
        self.threads_changed.emit()

    def open_by_fio(self, fio: str) -> None:
        needle = (fio or "").strip()
        if not needle:
            return
        lowered = needle.casefold()
        for thread in list(self._local_threads.values()) + list(self._threads):
            if thread.id == _VIRTUAL_SUPPORT:
                continue
            if thread.title.strip().casefold() == lowered:
                self.open_existing_dialog(thread.id)
                return
        try:
            users = self._api.directory(needle)
        except ApiError:
            users = []
        me_id = self._user.id if self._user is not None else ""
        me_fio = (self._user.fio if self._user is not None else "").casefold()
        peer: DirectoryUser | None = None
        for user in users:
            if user.fio.strip().casefold() != lowered:
                continue
            if me_id and user.id == me_id:
                continue
            if me_fio and user.fio.casefold() == me_fio:
                continue
            peer = user
            break
        if peer is None:
            if me_fio and lowered == me_fio:
                return
            peer = DirectoryUser(id="", fio=needle)
        self._start_dm(peer)

    def set_user(self, user: UserProfile | None) -> None:
        previous = self._user.id if self._user is not None else ""
        self._user = user
        support = bool(user and user.is_support)
        self._support_box.setVisible(support)
        self._support_caption.setVisible(support)
        self._shelf.setVisible(support)
        self._left_wrap.setVisible(support)
        if user is not None and user.id != previous:
            self._local = load_history(user.id)
            self._local_threads = {item.id: item for item in load_dialogs(user.id)}
            roster_upsert(user.id, user.fio, user.position)
            self._sync_roster_threads()
            self._reload_threads()
            return
        self.threads_changed.emit()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._place_down_btn()
        self._fit_thread_items()

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
        peer_id = str(payload.get("peer_id") or "")
        if kind == "chat_message":
            incoming = self._ingest_remote_message(payload)
            client_id = incoming.client_id if incoming is not None else ""
            pending = self._pending.pop(client_id, None) if client_id else None
            if pending is not None:
                self._set_receipt(client_id, "delivered")
            viewing = incoming is not None and self._is_viewing(
                incoming.thread_id,
                incoming.sender_id if not incoming.mine else peer_id,
            )
            if viewing or (thread_id and self._current in {"", _VIRTUAL_SUPPORT}):
                self._current = incoming.thread_id if incoming is not None else thread_id
            if incoming is not None and self._is_viewing(
                incoming.thread_id,
                incoming.sender_id if not incoming.mine else "",
            ):
                already = bool(client_id and client_id in self._bubbles)
                if already:
                    self._set_receipt(client_id, "delivered")
                else:
                    rows = self._collect_local_rows(incoming.thread_id)
                    if rows:
                        self._shared_stamp = rows[-1].id
                        self._render_rows(rows, pin_bottom=self._stick_bottom)
            self._reload_threads(remote=False)
            return
        if kind == "thread_opened" and thread_id:
            self._bind_ids(thread_id, peer_id)
            if self._is_viewing(thread_id, peer_id) or self._current in {"", _VIRTUAL_SUPPORT} or (
                peer_id and self._current == peer_id
            ):
                self._current = thread_id
            self._reload_threads()
            self._select_thread(self._current or thread_id)
            if self._is_viewing(thread_id, peer_id):
                self._load_messages(thread_id, pin_bottom=True)
            return
        if kind in {"chat_receipt", "ticket_updated", "presence"}:
            self._reload_threads()
            if self._current and self._current != _VIRTUAL_SUPPORT:
                self._load_messages(self._current, pin_bottom=self._stick_bottom)
            if kind == "ticket_updated" and self._user and self._user.is_support:
                self._reload_support()

    def _activity_fingerprint(self) -> tuple:
        return tuple(
            (item.id, item.last_message_at, item.preview, item.unread, item.pinned)
            for item in self._local_threads.values()
        )

    def _apply_activity(self, thread: ChatThread, rows: list[ChatMessage], *, viewing: bool) -> None:
        if not rows:
            return
        last = rows[-1]
        thread.preview = preview_of(last) or thread.preview
        thread.last_message_at = last.created_at
        if thread.id != _VIRTUAL_SUPPORT:
            self._local[thread.id] = rows
        if viewing:
            thread.unread = 0
            thread.last_read_id = last.id
            return
        if not thread.last_read_id:
            if thread.id in self._fresh_ids:
                thread.unread = sum(1 for item in rows if not item.mine)
            else:
                thread.last_read_id = last.id
                thread.unread = 0
            return
        unread = 0
        seen = False
        for item in rows:
            if item.id == thread.last_read_id:
                seen = True
                continue
            if seen and not item.mine:
                unread += 1
        thread.unread = unread

    def _sync_roster_threads(self) -> None:
        if self._user is None:
            return
        for thread in list(self._local_threads.values()):
            if thread.id == _VIRTUAL_SUPPORT or thread.kind == "support":
                continue
            peer_id = thread.peer_id or thread.id
            shared = load_shared(self._user.id, peer_id)
            local = self._local.get(thread.id) or []
            rows = shared or local
            if rows:
                self._apply_activity(thread, rows, viewing=thread.id == self._current)
        support_rows = self._local.get(_VIRTUAL_SUPPORT) or []
        if support_rows:
            support = self._local_threads.get(_VIRTUAL_SUPPORT)
            if support is None:
                support = _support_thread()
                self._local_threads[_VIRTUAL_SUPPORT] = support
            self._apply_activity(support, support_rows, viewing=self._current == _VIRTUAL_SUPPORT)

    def _collect_local_rows(self, thread_id: str) -> list[ChatMessage]:
        canon = self._canon(thread_id)
        peer = self._peer_for(canon) or self._peer_for(thread_id)
        merged: list[ChatMessage] = []
        seen: set[str] = set()

        def _add(rows: list[ChatMessage]) -> None:
            for item in rows:
                key = item.id or item.client_id
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                merged.append(item)

        _add(self._local.get(canon) or [])
        if thread_id != canon:
            _add(self._local.get(thread_id) or [])
        if self._user is not None:
            for key in (canon, thread_id, peer):
                if key:
                    _add(load_shared(self._user.id, key))
        merged.sort(key=lambda item: item.created_at or "")
        return merged

    def _poll_shared(self) -> None:
        if self._user is None:
            return
        before = self._activity_fingerprint()
        self._sync_roster_threads()
        after = self._activity_fingerprint()
        if self._current and self._current != _VIRTUAL_SUPPORT:
            rows = self._collect_local_rows(self._current)
            stamp = rows[-1].id if rows else self._shared_stamp
            if rows and stamp != self._shared_stamp:
                self._shared_stamp = stamp
                self._local[self._canon(self._current)] = rows
                thread = self._local_threads.get(self._canon(self._current)) or self._local_threads.get(
                    self._current
                )
                if thread is not None:
                    self._apply_activity(thread, rows, viewing=True)
                self._render_rows(rows, pin_bottom=self._stick_bottom)
        if before != after:
            self._persist()
            self._reload_threads(remote=False)

    def _reload_threads(self, *, remote: bool = True) -> None:
        needle = self._search.text().strip().casefold()
        fetched: list[ChatThread] = []
        if remote and self._api_chat:
            try:
                fetched = [
                    item
                    for item in self._api.threads(self._search.text().strip())
                    if item.id != _VIRTUAL_SUPPORT
                ]
                self._remote_cache = fetched
            except ApiError:
                self._api_chat = False
                fetched = []
        remote_rows = fetched if remote else list(self._remote_cache)
        local_rows = self._local.get(_VIRTUAL_SUPPORT) or []
        last = local_rows[-1] if local_rows else None
        stored_support = self._local_threads.get(_VIRTUAL_SUPPORT)
        support = stored_support or _support_thread(preview_of(last), last.created_at if last else "")
        if last is not None:
            self._apply_activity(support, local_rows, viewing=self._current == _VIRTUAL_SUPPORT)
        hay = " ".join([support.title, support.position, support.preview]).casefold()
        remote_ids = {item.id for item in remote_rows}
        local_dms: list[ChatThread] = []
        for thread in self._local_threads.values():
            if thread.id in remote_ids or thread.id == _VIRTUAL_SUPPORT:
                continue
            rows = self._local.get(thread.id) or []
            if self._user is not None:
                shared = load_shared(self._user.id, thread.id)
                if shared:
                    rows = shared
            if rows:
                self._apply_activity(thread, rows, viewing=thread.id == self._current)
            if not self._dialog_has_messages(thread):
                continue
            blob = " ".join([thread.title, thread.position, thread.preview]).casefold()
            if needle and needle not in blob:
                continue
            local_dms.append(thread)
        remote_rows = [item for item in remote_rows if self._dialog_has_messages(item)]
        visible = local_dms + remote_rows
        if self._user and self._user.is_support and (not needle or needle in hay):
            visible = [support] + visible
        self._threads = sort_threads(dedupe_dm_threads(visible))
        current = self._current or _VIRTUAL_SUPPORT
        self._list.blockSignals(True)
        self._list.clear()
        selected = -1
        for index, thread in enumerate(self._threads):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, thread.id)
            card = ThreadCard(thread, selected=thread.id == current)
            card.clicked.connect(self._open_thread)
            card.pin_toggled.connect(self._toggle_pin)
            item.setSizeHint(QSize(self._list_item_width(), 74))
            self._list.addItem(item)
            self._list.setItemWidget(item, card)
            if thread.id == current:
                selected = index
        if selected >= 0:
            self._list.setCurrentRow(selected)
        elif self._list.count() and current == _VIRTUAL_SUPPORT:
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)
        self._fit_thread_items()
        self.threads_changed.emit()

    def _list_item_width(self) -> int:
        return max(180, self._list.viewport().width() - 4)

    def _fit_thread_items(self) -> None:
        width = self._list_item_width()
        for index in range(self._list.count()):
            item = self._list.item(index)
            item.setSizeHint(QSize(width, 74))

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
        if thread_id and thread_id != self._current:
            self._open_thread(thread_id)

    def _paint_selection(self) -> None:
        for index in range(self._list.count()):
            item = self._list.item(index)
            card = self._list.itemWidget(item)
            thread_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
            if isinstance(card, ThreadCard):
                card.set_selected(thread_id == self._current)
                if thread_id == self._current:
                    card.set_unread(0)
        self._select_thread(self._current)

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
        if self._opening or not thread_id:
            return
        self._opening = True
        try:
            self._show_thread(thread_id)
        finally:
            self._opening = False

    def _show_thread(self, thread_id: str) -> None:
        self._current = thread_id
        self._paint_selection()
        thread = next(
            (
                item
                for item in list(self._threads) + list(self._local_threads.values())
                if item.id == thread_id or item.peer_id == thread_id
            ),
            None,
        )
        if thread_id == _VIRTUAL_SUPPORT and thread is None:
            thread = _support_thread()
        self._peer.setText(thread.title if thread else "Диалог")
        peer_id = ""
        if thread is not None:
            peer_id = thread.peer_id or ("" if thread.id.startswith("thr-") else thread.id)
        self._set_avatar(thread.title if thread else "", peer_id=peer_id)
        self._sync_pin_button(thread)
        rows = self._collect_local_rows(thread_id) if thread is not None else []
        if thread is not None:
            if rows:
                self._local[self._canon(thread_id)] = rows
                self._apply_activity(thread, rows, viewing=True)
            else:
                thread.unread = 0
            self._persist()
        if thread_id == _VIRTUAL_SUPPORT:
            self._meta.setText("Агент поддержки · в сети · профиль")
        else:
            labels = []
            if thread:
                labels = [thread.position]
                if thread.online:
                    labels.append("в сети")
                labels.append({"busy": "занят", "away": "не активен"}.get(thread.activity_status, ""))
            labels.append("профиль")
            self._meta.setText(" · ".join(part for part in labels if part))
        self._stick_bottom = True
        if thread_id == _VIRTUAL_SUPPORT:
            self._ensure_support_welcome()
            self._render_rows(self._collect_local_rows(thread_id), pin_bottom=True)
        elif rows:
            self._render_rows(rows, pin_bottom=True)
        else:
            self._clear_feed()
        self._pending_remote_thread = thread_id
        QTimer.singleShot(0, lambda tid=thread_id: self._load_remote_if_current(tid))

    def _load_remote_if_current(self, thread_id: str) -> None:
        if thread_id != self._current or thread_id != self._pending_remote_thread:
            return
        if thread_id == _VIRTUAL_SUPPORT:
            return
        self._load_messages(thread_id, pin_bottom=True)
        if self._api_chat:
            try:
                self._api.command({"type": "mark_read", "thread_id": thread_id})
            except ApiError:
                self._api_chat = False

    def _clear_feed(self) -> None:
        while self._feed.count() > 1:
            item = self._feed.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rendered_keys = []
        self._rendered_day = ""
        self._bubbles.clear()

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

    def _message_key(self, message: ChatMessage) -> str:
        return str(message.id or message.client_id or "")

    def _append_row_widget(self, message: ChatMessage) -> None:
        day = _message_day(message.created_at)
        if day and day != self._rendered_day:
            self._rendered_day = day
            self._feed.insertWidget(
                self._feed.count() - 1,
                DateSeparator(_date_label(message.created_at)),
                0,
                Qt.AlignmentFlag.AlignHCenter,
            )
        pending = self._pending.get(message.client_id)
        if pending is not None and pending.receipt == "failed":
            message.receipt = "failed"
        bubble = MessageBubble(message)
        bubble.agent_opened.connect(self._open_agent_card)
        bubble.attachment_requested.connect(self._save_attachment)
        if message.client_id:
            self._bubbles[message.client_id] = bubble
        self._feed.insertWidget(self._feed.count() - 1, bubble)

    def _render_rows(self, rows: list[ChatMessage], *, pin_bottom: bool = True) -> None:
        new_keys = [key for key in (self._message_key(item) for item in rows) if key]
        old_keys = list(self._rendered_keys)
        can_append = bool(old_keys) and new_keys[: len(old_keys)] == old_keys
        if can_append:
            known = set(old_keys)
            for message in rows:
                key = self._message_key(message)
                if key and key in known:
                    continue
                self._append_row_widget(message)
            self._rendered_keys = new_keys
        else:
            self._clear_feed()
            for message in rows:
                self._append_row_widget(message)
            self._rendered_keys = new_keys
        self._sync_info_panel(rows)
        if pin_bottom:
            self._scroll_to_bottom(force=True)

    def _current_thread(self) -> ChatThread | None:
        if self._current == _VIRTUAL_SUPPORT:
            return _support_thread()
        current = self._canon(self._current)
        found = self._local_threads.get(current) or self._local_threads.get(self._current)
        if found is not None:
            return found
        return next(
            (
                item
                for item in self._threads
                if item.id in {self._current, current} or item.peer_id in {self._current, current}
            ),
            None,
        )

    def _sync_info_panel(self, rows: list[ChatMessage] | None = None) -> None:
        thread = self._current_thread()
        if thread is None or thread.id == _VIRTUAL_SUPPORT or thread.kind == "support":
            self._info_panel.hide()
            return
        self._info_panel.show()
        data = rows if rows is not None else self._collect_local_rows(thread.id)
        self._info_panel.set_thread(thread, data)
        peer_id = thread.peer_id or ("" if thread.id.startswith("thr-") else thread.id)
        cached = peek_avatar(peer_id)
        if cached is not None:
            self._info_panel.set_avatar_pixmap(peer_id, cached)

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
        self._render_rows(self._collect_local_rows(thread_id), pin_bottom=True)

    def _load_messages(self, thread_id: str, *, pin_bottom: bool = True) -> None:
        if not thread_id:
            self._render_rows([], pin_bottom=pin_bottom)
            return
        canon = self._canon(thread_id)
        peer = self._peer_for(canon) or self._peer_for(thread_id)
        merged = self._collect_local_rows(thread_id)
        seen = {item.id or item.client_id for item in merged if item.id or item.client_id}

        def _add(rows: list[ChatMessage]) -> None:
            for item in rows:
                key = item.id or item.client_id
                if key and key in seen:
                    continue
                if key:
                    seen.add(key)
                merged.append(item)

        if self._api_chat and thread_id != _VIRTUAL_SUPPORT:
            for key in dict.fromkeys([canon, thread_id, peer]):
                if not key or key == _VIRTUAL_SUPPORT:
                    continue
                try:
                    _add(self._api.messages(key))
                    self._bind_ids(canon if canon.startswith("thr-") else key, peer)
                    break
                except ApiError:
                    continue
        merged.sort(key=lambda item: item.created_at or "")
        self._local[canon] = merged
        if merged:
            self._shared_stamp = merged[-1].id
        self._render_rows(merged, pin_bottom=pin_bottom)

    def _set_avatar(self, name: str, *, peer_id: str = "") -> None:
        parts = [part for part in (name or "").split() if part]
        initials = "?"
        if len(parts) == 1:
            initials = parts[0][:1].upper()
        elif parts:
            initials = (parts[0][:1] + parts[1][:1]).upper()
        self._avatar.setPixmap(QPixmap())
        self._avatar.setText(initials)
        self._avatar_peer_id = peer_id
        if not peer_id:
            return
        cached = peek_avatar(peer_id)
        if cached is not None:
            self._apply_header_avatar(cached)
            return
        Thread(target=self._fetch_header_avatar, args=(peer_id,), daemon=True).start()

    def _fetch_header_avatar(self, peer_id: str) -> None:
        try:
            pixmap = load_peer_avatar(self._client, peer_id)
        except Exception:
            pixmap = QPixmap()
        self._avatar_ready.emit(peer_id, pixmap)

    def _on_avatar_ready(self, peer_id: str, pixmap: object) -> None:
        if peer_id != getattr(self, "_avatar_peer_id", ""):
            return
        if isinstance(pixmap, QPixmap):
            self._apply_header_avatar(pixmap)

    def _apply_header_avatar(self, pixmap: QPixmap) -> None:
        if pixmap.isNull():
            return
        self._avatar.setText("")
        self._avatar.setPixmap(circular_pixmap(pixmap, 40))
        self._info_panel.set_avatar_pixmap(getattr(self, "_avatar_peer_id", ""), pixmap)

    def _open_profile(self) -> None:
        thread = next((item for item in self._threads if item.id == self._current), None)
        if thread is None and self._current == _VIRTUAL_SUPPORT:
            thread = _support_thread()
        if thread is None:
            return
        ChatProfileDialog(thread, self).exec()

    def _open_agent_card(self, agent: object, mine: bool) -> None:
        payload = agent if isinstance(agent, dict) else {}
        dialog = AgentOfferDialog(payload, mine=mine, parent=self)
        dialog.exec()
        if mine or dialog.decision != AgentOfferDialog.ACCEPTED:
            return
        workflow_id = str(payload.get("workflow_id") or "").strip()
        title = str(payload.get("title") or "ИИ-агент")
        if workflow_id:
            try:
                record = self._client.get_workflow(workflow_id)
                self.open_agent_requested.emit(record.id, record.title or title)
                return
            except ApiError:
                pass
        notes = "\n".join(
            part
            for part in (
                f"Агент из чата: {title}",
                str(payload.get("description") or ""),
                f"Цель: {payload.get('goal') or ''}",
                f"Триггер: {payload.get('trigger_summary') or payload.get('trigger_kind') or ''}",
            )
            if part
        )
        try:
            created = self._client.create_workflow(notes=notes, file_paths=[])
        except ApiError as exc:
            QMessageBox.warning(self, "Агент", exc.message or "Не удалось добавить агента.")
            return
        QMessageBox.information(self, "Агент", f"«{created.title or title}» добавлен в ваши агенты.")
        self.open_agent_requested.emit(created.id, created.title or title)

    def _sync_pin_button(self, thread: ChatThread | None) -> None:
        if thread is None:
            self._pin_btn.hide()
            return
        self._pin_btn.show()
        self._pin_btn.blockSignals(True)
        self._pin_btn.setChecked(thread.pinned)
        self._pin_btn.setText("Открепить" if thread.pinned else "Закрепить")
        self._pin_btn.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none;"
            " border-radius: 10px; padding: 0 12px; }"
            "QPushButton:hover { background: #0A8670; }"
            if thread.pinned
            else
            "QPushButton { background: #FFFFFF; color: #08745F;"
            " border: 1px solid #08745F; border-radius: 10px; padding: 0 12px; }"
            "QPushButton:hover { background: #EAF7F3; }"
        )
        self._pin_btn.blockSignals(False)
        self._pin_btn.setToolTip("Чат закреплён — нажмите, чтобы открепить" if thread.pinned else "Закрепить чат сверху списка")

    def _toggle_current_pin(self) -> None:
        if self._current:
            self._toggle_pin(self._current)

    def _toggle_pin(self, thread_id: str) -> None:
        if not thread_id:
            return
        thread = self._local_threads.get(thread_id)
        if thread is None:
            thread = next((item for item in self._threads if item.id == thread_id), None)
            if thread is None:
                return
            self._local_threads[thread_id] = thread
        thread.pinned = not thread.pinned
        self._persist()
        self._reload_threads()
        if thread_id == self._current:
            self._sync_pin_button(thread)

    def _persist(self) -> None:
        if self._user is None:
            return
        save_history(self._user.id, self._local, list(self._local_threads.values()))

    def _store_local(self, message: ChatMessage) -> None:
        self._local.setdefault(message.thread_id or _VIRTUAL_SUPPORT, []).append(message)
        self._persist()

    def _open_new(self) -> None:
        try:
            users = self._api.directory()
        except ApiError as exc:
            QMessageBox.warning(
                self,
                "Новый чат",
                exc.message or "Не удалось загрузить реестр сотрудников 1С.",
            )
            return
        me = self._user.id if self._user is not None else ""
        me_fio = (self._user.fio if self._user is not None else "").casefold()
        peers = [
            user
            for user in users
            if (not me or user.id != me) and (not me_fio or user.fio.casefold() != me_fio)
        ]
        if not peers:
            QMessageBox.information(self, "Новый чат", "В реестре 1С нет других сотрудников.")
            return
        dialog = UserPickerDialog(peers, self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.chosen is None:
            return
        self._start_dm(dialog.chosen)

    def _find_existing_dm(self, peer: DirectoryUser) -> ChatThread | None:
        peer_id = (peer.id or "").strip()
        fio = (peer.fio or "").strip().casefold()
        for thread in list(self._local_threads.values()) + list(self._threads):
            if thread.id == _VIRTUAL_SUPPORT or thread.kind == "support":
                continue
            if peer_id and (thread.peer_id == peer_id or thread.id == peer_id):
                return thread
            if fio and thread.title.strip().casefold() == fio:
                return thread
        return None

    def _start_dm(self, peer: DirectoryUser) -> None:
        existing = self._find_existing_dm(peer)
        thread_id = (existing.id if existing is not None else "") or peer.id or f"dm:{peer.fio}"
        thread = existing or self._local_threads.get(thread_id) or ChatThread(
            id=thread_id,
            kind="dm",
            title=peer.fio,
            position=peer.position or peer.department or "Сотрудник 1С",
            preview="Нет сообщений",
            peer_id=peer.id,
        )
        if peer.fio:
            thread.title = peer.fio
        if peer.position or peer.department:
            thread.position = peer.position or peer.department
        if peer.department:
            thread.department = peer.department
        thread.peer_id = peer.id or thread.peer_id
        self._local_threads[thread_id] = thread
        self._local.setdefault(thread_id, [])
        self._persist()
        if peer.id:
            self._bind_ids(thread_id, peer.id)
            try:
                self._api.command({"type": "open_dm", "peer_id": peer.id})
            except ApiError:
                self._api_chat = False
        self._current = thread_id
        self._reload_threads()
        self._select_thread(thread_id)
        self._open_thread(thread_id)

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

    def _save_attachment(self, attachment: object) -> None:
        if not isinstance(attachment, ChatAttachment):
            return
        if not attachment.id:
            QMessageBox.warning(self, "Файл", "Файл ещё не готов к скачиванию.")
            return
        default_name = attachment.filename or "file"
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить файл", default_name)
        if not path:
            return
        try:
            data = self._client.fetch_bytes(f"/api/v1/chat/files/{attachment.id}")
            Path(path).write_bytes(data)
        except ApiError as exc:
            QMessageBox.warning(self, "Файл", exc.message or "Не удалось скачать файл.")
        except OSError as exc:
            QMessageBox.warning(self, "Файл", str(exc) or "Не удалось сохранить файл.")

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
        raw_id = _VIRTUAL_SUPPORT if support else self._current
        thread_id = raw_id if support else self._canon(raw_id)
        peer_id = "" if support else (self._peer_for(thread_id) or self._peer_for(raw_id))
        client_id = uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        attachments_meta = self._describe_files(files)
        file_ids = [str(item["file_id"]) for item in attachments_meta]
        payload = {
            "type": "send_message",
            "client_id": client_id,
            "thread_id": "" if support else thread_id,
            "peer_id": peer_id,
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
            receipt="sending" if support else "delivered",
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
        self._append_row_widget(optimistic)
        if client_id not in self._rendered_keys:
            self._rendered_keys.append(client_id)
        self._scroll_to_bottom(force=True)
        target = self._local_threads.get(thread_id) or self._local_threads.get(raw_id)
        if target is None:
            target = next((item for item in self._threads if item.id in {thread_id, raw_id}), None)
            if target is not None:
                self._local_threads[thread_id] = target
        if target is not None:
            target.preview = preview_of(optimistic) or target.preview
            target.last_message_at = created_at
            target.unread = 0
            target.last_read_id = client_id
            if peer_id:
                target.peer_id = peer_id
        if not support and self._user is not None:
            optimistic.receipt = "delivered"
            self._set_receipt(client_id, "delivered")
            self._pending.pop(client_id, None)
        queued = False
        for index, (path, meta) in enumerate(zip(files, attachments_meta)):
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
                if 0 <= index < len(optimistic.attachments):
                    optimistic.attachments[index].id = remote_id
                    optimistic.attachments[index].filename = str(meta["filename"])
                    optimistic.attachments[index].mime = str(meta["mime"])
                    optimistic.attachments[index].size = int(meta["size"] or 0)
        payload["file_ids"] = [str(item["file_id"]) for item in attachments_meta]
        payload["files"] = attachments_meta
        if not support and self._user is not None:
            append_shared(self._user.id, peer_id or thread_id, optimistic)
            if peer_id and peer_id != thread_id:
                append_shared(self._user.id, thread_id, optimistic)
            self._store_local(optimistic)
            self._shared_stamp = optimistic.id
        try:
            self._api.command(payload)
            queued = True
            QTimer.singleShot(_SEND_TIMEOUT_MS, lambda: self._fail_if_pending(client_id))
        except ApiError:
            self._api_chat = False
            if support or (self._user is not None and not support):
                self._set_receipt(client_id, "delivered")
                self._pending.pop(client_id, None)
                if support:
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
            self._input.setPlaceholderText("Напишите сообщение...")
            self._pending_files.clear()
            self._refresh_file_chips()
        self._reload_threads(remote=False)

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
