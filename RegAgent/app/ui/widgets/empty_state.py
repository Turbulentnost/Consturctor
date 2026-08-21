from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.styles import primary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class EmptyState(QWidget):
    action_clicked = Signal()

    def __init__(
        self,
        title: str,
        subtitle: str = "",
        *,
        action: str = "",
        glyph: str = "◇",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")

        icon = QLabel(glyph)
        icon.setFixedSize(56, 56)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFont(app_font(22, QFont.Weight.DemiBold))
        icon.setStyleSheet(
            "color: #08745F; background: #EAF7F3; border-radius: 28px;"
        )

        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setFont(app_font(18, QFont.Weight.DemiBold))
        heading.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        caption = QLabel(subtitle)
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setFont(app_font(13))
        caption.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        caption.setVisible(bool(subtitle))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 36, 24, 36)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(heading)
        layout.addWidget(caption)
        if action:
            button = QPushButton(action)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedHeight(40)
            button.setFont(app_font(13, QFont.Weight.DemiBold))
            button.setStyleSheet(primary_button_qss(radius=12))
            button.clicked.connect(self.action_clicked.emit)
            layout.addSpacing(8)
            layout.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
