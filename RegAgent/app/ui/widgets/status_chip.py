from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QWidget

from app.ui.styles import chip_qss
from app.ui.theme import app_font


class StatusChip(QLabel):
    def __init__(
        self,
        text: str = "",
        *,
        variant: str = "neutral",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFont(app_font(11, QFont.Weight.DemiBold))
        self.set_variant(variant)

    def set_variant(self, variant: str) -> None:
        self.setStyleSheet(chip_qss(variant))
