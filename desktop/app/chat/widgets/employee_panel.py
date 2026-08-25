from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.chat.models import ChatAttachment, ChatMessage, ChatThread
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, circular_pixmap, scroll_bar_qss


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[1][:1]).upper()


def _format_size(size: int) -> str:
    if size <= 0:
        return ""
    if size < 1024 * 1024:
        return f"{max(1, round(size / 1024))} КБ"
    return f"{size / (1024 * 1024):.1f} МБ".replace(".", ",")


class EmployeePanel(QWidget):
    profile_requested = Signal()
    agent_opened = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._peer_id = ""
        self.setFixedWidth(320)
        self.setStyleSheet("background: #FFFFFF; border-left: 1px solid rgba(6,72,61,0.08);")

        title = QLabel("О сотруднике")
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")

        self._avatar = QLabel("?")
        self._avatar.setFixedSize(72, 72)
        self._avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._avatar.setFont(app_font(22, QFont.Weight.DemiBold))
        self._avatar.setStyleSheet("background: #D8EFE6; color: #006B55; border-radius: 36px; border: none;")

        self._name = QLabel("Выберите диалог")
        self._name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._name.setWordWrap(True)
        self._name.setFont(app_font(14, QFont.Weight.DemiBold))
        self._name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")

        self._position = QLabel("")
        self._position.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._position.setWordWrap(True)
        self._position.setFont(app_font(11))
        self._position.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; border: none;")

        self._status = QLabel("")
        self._status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status.setFont(app_font(11, QFont.Weight.DemiBold))
        self._status.setStyleSheet("color: #08745F; background: transparent; border: none;")

        self._materials = QVBoxLayout()
        self._materials.setContentsMargins(0, 0, 0, 0)
        self._materials.setSpacing(8)

        self._agents = QVBoxLayout()
        self._agents.setContentsMargins(0, 0, 0, 0)
        self._agents.setSpacing(8)

        content = QWidget()
        content.setStyleSheet("background: transparent; border: none;")
        col = QVBoxLayout(content)
        col.setContentsMargins(18, 16, 18, 16)
        col.setSpacing(14)
        col.addWidget(title)
        col.addWidget(self._avatar, 0, Qt.AlignmentFlag.AlignHCenter)
        col.addWidget(self._name)
        col.addWidget(self._position)
        col.addWidget(self._status)
        col.addSpacing(10)
        col.addWidget(self._section("Общие материалы"))
        col.addLayout(self._materials)
        col.addSpacing(8)
        col.addWidget(self._section("Связанные агенты"))
        col.addLayout(self._agents)
        col.addStretch(1)

        self._profile = QPushButton("Открыть профиль")
        self._profile.setCursor(Qt.CursorShape.PointingHandCursor)
        self._profile.setFixedHeight(42)
        self._profile.setStyleSheet(
            "QPushButton { background: transparent; color: #08745F;"
            " border: 1px solid rgba(8,116,95,0.65); border-radius: 12px; }"
            "QPushButton:hover { background: #F3FAF7; }"
        )
        self._profile.clicked.connect(self.profile_requested.emit)
        col.addWidget(self._profile)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }" + scroll_bar_qss())

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(scroll)

    def set_thread(self, thread: ChatThread | None, messages: list[ChatMessage]) -> None:
        if thread is None:
            self._peer_id = ""
            self._avatar.setText("?")
            self._avatar.setPixmap(QPixmap())
            self._name.setText("Выберите диалог")
            self._position.setText("")
            self._status.setText("")
            self._clear(self._materials)
            self._clear(self._agents)
            return
        self._peer_id = thread.peer_id or ("" if thread.id.startswith("thr-") else thread.id)
        self._avatar.setPixmap(QPixmap())
        self._avatar.setText(_initials(thread.title))
        self._name.setText(thread.title or "Диалог")
        self._position.setText(thread.position or "Должность не указана")
        status = "В сети" if thread.online else {"busy": "Занят", "away": "Не активен"}.get(
            thread.activity_status,
            "Не в сети",
        )
        self._status.setText(status)
        self._fill_materials(messages)
        self._fill_agents(messages)

    def set_avatar_pixmap(self, peer_id: str, pixmap: QPixmap) -> None:
        if not peer_id or peer_id != self._peer_id or pixmap.isNull():
            return
        self._avatar.setText("")
        self._avatar.setPixmap(circular_pixmap(pixmap, 72))

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(app_font(12, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")
        return label

    def _clear(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _fill_materials(self, messages: list[ChatMessage]) -> None:
        self._clear(self._materials)
        seen: set[str] = set()
        attachments: list[ChatAttachment] = []
        for message in messages:
            for item in message.attachments:
                key = item.id or item.filename
                if key in seen:
                    continue
                seen.add(key)
                attachments.append(item)
        if not attachments:
            self._materials.addWidget(self._empty("Нет общих материалов"))
            return
        for item in attachments[-8:]:
            self._materials.addWidget(self._material_card(item))

    def _fill_agents(self, messages: list[ChatMessage]) -> None:
        self._clear(self._agents)
        seen: set[str] = set()
        agents: list[dict] = []
        for message in messages:
            if not message.agent:
                continue
            key = str(message.agent.get("workflow_id") or message.agent.get("title") or "")
            if key in seen:
                continue
            seen.add(key)
            agents.append(message.agent)
        if not agents:
            self._agents.addWidget(self._empty("Нет связанных агентов"))
            return
        for agent in agents[-6:]:
            self._agents.addWidget(self._agent_card(agent))

    def _empty(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setFont(app_font(11))
        label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; border: none;")
        return label

    def _material_card(self, item: ChatAttachment) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.10); border-radius: 12px; }"
        )
        icon = QLabel((item.filename.rsplit(".", 1)[-1][:3] or "FILE").upper())
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFont(app_font(9, QFont.Weight.DemiBold))
        icon.setStyleSheet("background: #EAF7F3; color: #08745F; border-radius: 9px; border: none;")
        name = QLabel(item.filename or "Файл")
        name.setFont(app_font(11, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")
        name.setWordWrap(True)
        meta = QLabel(" · ".join(part for part in [item.mime.split("/")[-1].upper(), _format_size(item.size)] if part))
        meta.setFont(app_font(10))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; border: none;")
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(name)
        text.addWidget(meta)
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        return card

    def _agent_card(self, agent: dict) -> QFrame:
        card = QFrame()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.10); border-radius: 12px; }"
            "QFrame:hover { background: #F3FAF7; border: 1px solid rgba(8,116,95,0.35); }"
        )
        title = str(agent.get("title") or "ИИ-агент")
        icon = QLabel((title[:1] or "А").upper())
        icon.setFixedSize(34, 34)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFont(app_font(13, QFont.Weight.DemiBold))
        icon.setStyleSheet("background: #D8EFE6; color: #08745F; border-radius: 17px; border: none;")
        name = QLabel(title)
        name.setFont(app_font(11, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent; border: none;")
        name.setWordWrap(True)
        meta = QLabel(str(agent.get("status") or agent.get("phase") or "Агент"))
        meta.setFont(app_font(10))
        meta.setStyleSheet("color: #08745F; background: #EAF7F3; border-radius: 9px; padding: 2px 8px;")
        text = QVBoxLayout()
        text.setSpacing(3)
        text.addWidget(name)
        text.addWidget(meta, 0, Qt.AlignmentFlag.AlignLeft)
        row = QHBoxLayout(card)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        row.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        card.mousePressEvent = lambda event, payload=agent: self.agent_opened.emit(payload)  # type: ignore[method-assign]
        return card
