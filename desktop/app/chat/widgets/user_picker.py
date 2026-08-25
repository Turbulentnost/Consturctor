from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.chat.models import DirectoryUser
from app.ui.theme import MAIN_TEXT, app_font, scroll_bar_qss


class UserPickerDialog(QDialog):
    def __init__(self, users: list[DirectoryUser], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.chosen: DirectoryUser | None = None
        self._users = users
        self.setWindowTitle("Новый чат")
        self.setModal(True)
        self.resize(460, 520)

        title = QLabel("Кому написать")
        title.setFont(app_font(18, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        hint = QLabel("Сотрудники из 1С. Выберите человека, чтобы открыть диалог.")
        hint.setFont(app_font(12))
        hint.setStyleSheet("color: #6B7773; background: transparent;")
        hint.setWordWrap(True)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по ФИО, должности, отделу…")
        self._search.setFont(app_font(13))
        self._search.setFixedHeight(36)
        self._search.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 1px solid rgba(6,72,61,0.12);"
            " border-radius: 12px; padding: 0 12px; color: #101817; }"
        )
        self._search.textChanged.connect(self._filter)

        self._list = QListWidget()
        self._list.setSpacing(4)
        self._list.setStyleSheet(
            """
            QListWidget { border: none; background: transparent; outline: none; }
            QListWidget::item { border: none; }
            QListWidget::item:selected { background: transparent; }
            """
            + scroll_bar_qss()
        )
        self._list.itemClicked.connect(self._on_item)

        self._empty = QLabel("Никого не найдено")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet("color: #6B7773; background: transparent;")
        self._empty.hide()

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)
        root.addWidget(title)
        root.addWidget(hint)
        root.addWidget(self._search)
        root.addWidget(self._list, 1)
        root.addWidget(self._empty)
        self._filter("")
        self._search.setFocus()

    def _filter(self, needle: str) -> None:
        query = needle.strip().casefold()
        self._list.clear()
        shown = 0
        for user in self._users:
            hay = " ".join([user.fio, user.position, user.department]).casefold()
            if query and query not in hay:
                continue
            row = self._row(user)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, user)
            item.setSizeHint(QSize(400, 64))
            self._list.addItem(item)
            self._list.setItemWidget(item, row)
            shown += 1
        self._empty.setVisible(shown == 0)
        self._list.setVisible(shown > 0)

    def _row(self, user: DirectoryUser) -> QWidget:
        host = QWidget()
        host.setStyleSheet(
            "QWidget { background: #FFFFFF; border: 1px solid rgba(8,116,95,0.12);"
            " border-radius: 12px; }"
        )
        icon = QLabel((user.fio[:1] or "?").upper())
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFixedSize(36, 36)
        icon.setFont(app_font(15, QFont.Weight.DemiBold))
        icon.setStyleSheet("background: #EAF7F3; color: #08745F; border-radius: 10px;")
        name = QLabel(user.fio)
        name.setFont(app_font(13, QFont.Weight.DemiBold))
        name.setStyleSheet("color: #101817; background: transparent; border: none;")
        meta = " · ".join(part for part in (user.position, user.department) if part) or "Сотрудник 1С"
        sub = QLabel(meta)
        sub.setFont(app_font(11))
        sub.setStyleSheet("color: #6B7773; background: transparent; border: none;")
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(name)
        text.addWidget(sub)
        row = QHBoxLayout(host)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        row.addWidget(icon, 0)
        row.addLayout(text, 1)
        host.setMinimumHeight(56)
        return host

    def _on_item(self, item: QListWidgetItem) -> None:
        user = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(user, DirectoryUser):
            self.chosen = user
            self.accept()
