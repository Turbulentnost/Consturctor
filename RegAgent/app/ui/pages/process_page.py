from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models import Card, FunctionGroup
from app.ui.styles import card_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font, scroll_bar_qss


class ProcessPickerPage(QWidget):
    selected = Signal(str)
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._card: Card | None = None

        title = QLabel("Выберите процесс")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        subtitle = QLabel("В регламенте несколько функциональных групп — выберите одну для паспорта")
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        subtitle.setWordWrap(True)

        self._list_host = QVBoxLayout()
        self._list_host.setSpacing(10)
        inner = QWidget()
        inner.setLayout(self._list_host)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }" + scroll_bar_qss()
        )

        back = QPushButton("Назад")
        back.setStyleSheet(secondary_button_qss(radius=12))
        back.clicked.connect(self.cancelled.emit)
        self._back_btn = back

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addWidget(scroll, 1)
        layout.addWidget(back, 0, Qt.AlignmentFlag.AlignRight)
        self._group_buttons: list[QPushButton] = []

    def set_actions_enabled(self, enabled: bool) -> None:
        self._back_btn.setEnabled(enabled)
        for btn in self._group_buttons:
            btn.setEnabled(enabled)

    def set_card(self, card: Card) -> None:
        self._card = card
        self._group_buttons.clear()
        while self._list_host.count():
            item = self._list_host.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for group in card.functions.groups:
            self._list_host.addWidget(self._group_card(group))
        self._list_host.addStretch(1)

    def _group_card(self, group: FunctionGroup) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet(card_qss("ProcessGroup", hover=True))
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        heading = QLabel(group.title)
        heading.setFont(app_font(16, QFont.Weight.DemiBold))
        desc = QLabel(group.summary or ", ".join(group.tools))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        btn = QPushButton("Выбрать")
        btn.setStyleSheet(primary_button_qss(compact=True))
        btn.clicked.connect(lambda _=False, gid=group.id: self.selected.emit(gid))
        self._group_buttons.append(btn)
        layout.addWidget(heading)
        layout.addWidget(desc)
        layout.addWidget(btn, 0, Qt.AlignmentFlag.AlignRight)
        return frame
