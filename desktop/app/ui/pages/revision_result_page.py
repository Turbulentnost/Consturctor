from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget

from app.api_client import RegulationRevisionResult
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class RevisionResultPage(QWidget):
    download_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._result: RegulationRevisionResult | None = None
        self._title = QLabel("Новая редакция регламента сформирована")
        self._title.setFont(app_font(26, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._subtitle = QLabel("Слева исходный текст, справа редакция, сформированная по ответам пользователя.")
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(app_font(13))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._source = QTextEdit()
        self._source.setReadOnly(True)
        self._source.setStyleSheet(_preview_qss())
        self._revised = QTextEdit()
        self._revised.setReadOnly(True)
        self._revised.setStyleSheet(_preview_qss())

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setFont(app_font(12))
        self._summary.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        download = QPushButton("Скачать DOCX")
        download.setCursor(Qt.CursorShape.PointingHandCursor)
        download.setStyleSheet(_primary_button_qss())
        download.clicked.connect(lambda: self.download_requested.emit("document"))
        protocol = QPushButton("Скачать протокол")
        protocol.setCursor(Qt.CursorShape.PointingHandCursor)
        protocol.setStyleSheet(_secondary_button_qss())
        protocol.clicked.connect(lambda: self.download_requested.emit("protocol"))

        actions = QHBoxLayout()
        actions.addWidget(download)
        actions.addWidget(protocol)
        actions.addStretch(1)

        previews = QHBoxLayout()
        previews.setSpacing(16)
        previews.addWidget(self._preview_card("Исходный документ", self._source), 1)
        previews.addWidget(self._preview_card("Исправленный документ", self._revised), 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addWidget(self._summary)
        layout.addLayout(actions)
        layout.addLayout(previews, 1)

    def set_result(self, result: RegulationRevisionResult) -> None:
        self._result = result
        self._source.setHtml(result.source_preview_html or "<p>Исходный preview недоступен.</p>")
        self._revised.setHtml(result.revised_preview_html or "<p>Исправленный preview недоступен.</p>")
        changed = len([item for item in result.diff_blocks if item.status == "changed"])
        self._summary.setText(f"{result.message}\nИзменённых блоков: {changed}")

    @staticmethod
    def _preview_card(title: str, editor: QTextEdit) -> QWidget:
        card = QFrame()
        card.setObjectName("PreviewCard")
        card.setStyleSheet(
            """
            QFrame#PreviewCard {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 18px;
            }
            """
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 14)
        header = QLabel(title)
        header.setFont(app_font(14, QFont.Weight.DemiBold))
        header.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(header)
        layout.addWidget(editor, 1)
        return card


def _preview_qss() -> str:
    return """
    QTextEdit {
        background: #FFFFFF;
        border: none;
        color: #101817;
        padding: 4px;
    }
    """


def _primary_button_qss() -> str:
    return """
    QPushButton {
        background: #08745F;
        color: #FFFFFF;
        border: none;
        border-radius: 12px;
        padding: 10px 16px;
    }
    QPushButton:hover { background: #0A806A; }
    """


def _secondary_button_qss() -> str:
    return """
    QPushButton {
        background: #FFFFFF;
        color: #08745F;
        border: 1px solid rgba(8,116,95,0.18);
        border-radius: 12px;
        padding: 10px 16px;
    }
    QPushButton:hover { background: rgba(8,116,95,0.05); }
    """
