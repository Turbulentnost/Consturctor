from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextEdit, QVBoxLayout, QWidget

from app.api_client import ApiClient, RegulationRevisionResult, RevisionPreviewPage
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class RevisionResultPage(QWidget):
    download_requested = Signal(str)

    def __init__(self, api: ApiClient | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._result: RegulationRevisionResult | None = None
        self._title = QLabel("Новая редакция регламента сформирована")
        self._title.setFont(app_font(26, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._subtitle = QLabel("Слева исходный текст, справа редакция, сформированная по ответам пользователя.")
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(app_font(13))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._source_scroll = self._page_scroll_area()
        self._source_pages = QVBoxLayout()
        self._source_pages.setContentsMargins(10, 10, 10, 10)
        self._source_pages.setSpacing(14)
        source_content = QWidget()
        source_content.setLayout(self._source_pages)
        source_content.setStyleSheet("background: #F5F7F7;")
        self._source_scroll.setWidget(source_content)

        self._revised_scroll = self._page_scroll_area()
        self._revised_pages = QVBoxLayout()
        self._revised_pages.setContentsMargins(10, 10, 10, 10)
        self._revised_pages.setSpacing(14)
        revised_content = QWidget()
        revised_content.setLayout(self._revised_pages)
        revised_content.setStyleSheet("background: #F5F7F7;")
        self._revised_scroll.setWidget(revised_content)
        self._syncing_scroll = False
        self._source_scroll.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_scroll(self._source_scroll, self._revised_scroll, value)
        )
        self._revised_scroll.verticalScrollBar().valueChanged.connect(
            lambda value: self._sync_scroll(self._revised_scroll, self._source_scroll, value)
        )

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setFont(app_font(12))
        self._summary.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        download = QPushButton("Скачать DOCX")
        download.setCursor(Qt.CursorShape.PointingHandCursor)
        download.setStyleSheet(_primary_button_qss())
        download.clicked.connect(lambda: self.download_requested.emit("document"))
        self._pdf_download = QPushButton("Скачать PDF")
        self._pdf_download.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pdf_download.setStyleSheet(_primary_button_qss())
        self._pdf_download.clicked.connect(lambda: self.download_requested.emit("pdf"))
        protocol = QPushButton("Скачать протокол")
        protocol.setCursor(Qt.CursorShape.PointingHandCursor)
        protocol.setStyleSheet(_secondary_button_qss())
        protocol.clicked.connect(lambda: self.download_requested.emit("protocol"))

        actions = QHBoxLayout()
        actions.addWidget(self._pdf_download)
        actions.addWidget(download)
        actions.addWidget(protocol)
        actions.addStretch(1)

        previews = QHBoxLayout()
        previews.setSpacing(16)
        previews.addWidget(self._preview_card("Исходный документ", self._source_scroll), 1)
        previews.addWidget(self._preview_card("Исправленный документ", self._revised_scroll), 1)

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
        self._pdf_download.setVisible(bool(result.pdf_download_url))
        if result.source_preview_pages and result.revised_preview_pages and self._api is not None:
            self._render_pages(self._source_pages, result.source_preview_pages, result.source_preview_html)
            self._render_pages(self._revised_pages, result.revised_preview_pages, result.revised_preview_html)
        else:
            self._render_html_fallback(self._source_pages, result.source_preview_html, "Исходный preview недоступен.")
            self._render_html_fallback(self._revised_pages, result.revised_preview_html, "Исправленный preview недоступен.")
        changed = len([item for item in result.diff_blocks if item.status == "changed"])
        self._summary.setText(f"{result.message}\nИзменённых блоков: {changed}")

    @staticmethod
    def _preview_card(title: str, preview: QWidget) -> QWidget:
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
        layout.addWidget(preview, 1)
        return card

    @staticmethod
    def _page_scroll_area() -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #F5F7F7; border: none; }")
        return scroll

    def _render_pages(self, layout: QVBoxLayout, pages: list[RevisionPreviewPage], fallback_html: str) -> None:
        _clear_layout(layout)
        rendered = 0
        for page in pages:
            if not page.image_url:
                continue
            try:
                data = self._api.fetch_bytes(page.image_url) if self._api is not None else b""
            except Exception:
                data = b""
            pixmap = QPixmap()
            if not data or not pixmap.loadFromData(data):
                continue
            label = QLabel()
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setPixmap(pixmap)
            label.setStyleSheet("background: #FFFFFF; border: 1px solid rgba(16,24,23,0.10);")
            layout.addWidget(label)
            rendered += 1
        if not rendered:
            self._render_html_fallback(layout, fallback_html, "Preview страниц недоступен.")
        else:
            layout.addStretch(1)

    @staticmethod
    def _render_html_fallback(layout: QVBoxLayout, html: str, empty_text: str) -> None:
        _clear_layout(layout)
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setStyleSheet(_preview_qss())
        editor.setHtml(html or f"<p>{empty_text}</p>")
        layout.addWidget(editor, 1)

    def _sync_scroll(self, source: QScrollArea, target: QScrollArea, value: int) -> None:
        if self._syncing_scroll:
            return
        self._syncing_scroll = True
        source_bar = source.verticalScrollBar()
        target_bar = target.verticalScrollBar()
        ratio = value / max(source_bar.maximum(), 1)
        target_bar.setValue(int(target_bar.maximum() * ratio))
        self._syncing_scroll = False


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


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
