from __future__ import annotations

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from app.api_client import RegulationRevisionResult
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class RevisionResultPage(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = QLabel("Копия регламента создана")
        self._title.setFont(app_font(26, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._body = QLabel("")
        self._body.setWordWrap(True)
        self._body.setFont(app_font(13))
        self._body.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        layout.addStretch(1)

    def set_result(self, result: RegulationRevisionResult) -> None:
        self._body.setText(
            f"{result.message}\n\nФайл: {result.document_path}\nПротокол: {result.protocol_path}"
        )
