from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.models import Card
from app.ui.styles import primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class SchedulePage(QWidget):
    finished = Signal()
    skipped = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("Расписание")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        subtitle = QLabel(
            "Автозапуск по расписанию пока недоступен в RegAgent. "
            "Агент будет запускаться вручную из списка."
        )
        subtitle.setWordWrap(True)
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        done = QPushButton("Готово → к списку агентов")
        done.setStyleSheet(primary_button_qss(radius=12))
        done.clicked.connect(self.finished.emit)

        skip = QPushButton("Пропустить")
        skip.setStyleSheet(secondary_button_qss(radius=12))
        skip.clicked.connect(self.skipped.emit)
        self._action_buttons = (done, skip)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addStretch(1)
        layout.addWidget(done, 0, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(skip, 0, Qt.AlignmentFlag.AlignRight)

    def set_card(self, _card: Card) -> None:
        return

    def set_actions_enabled(self, enabled: bool) -> None:
        for btn in self._action_buttons:
            btn.setEnabled(enabled)
