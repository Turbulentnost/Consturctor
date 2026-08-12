from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy, QTextEdit, QVBoxLayout, QWidget

from app.api_client import ApiClient, RegulationRevisionResult, RevisionPreviewPage
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class PageImageLabel(QLabel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

    def set_source_pixmap(self, pixmap: QPixmap) -> None:
        self._source = pixmap
        self._rescale()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self) -> None:
        if self._source.isNull():
            return
        width = max(240, self.width() - 8)
        scaled = self._source.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(scaled)
        self.setMinimumHeight(scaled.height() + 2)


class RevisionResultPage(QWidget):
    download_requested = Signal(str)

    def __init__(self, api: ApiClient | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._result: RegulationRevisionResult | None = None
        self._source_page_widgets: dict[int, QWidget] = {}
        self._revised_page_widgets: dict[int, QWidget] = {}
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

        self._changes_wrap = QWidget()
        self._changes_wrap.setStyleSheet("background: transparent;")
        self._changes_layout = QHBoxLayout(self._changes_wrap)
        self._changes_layout.setContentsMargins(0, 0, 0, 0)
        self._changes_layout.setSpacing(8)

        self._previews_wrap = QWidget()
        self._previews_wrap.setStyleSheet("background: transparent;")
        self._previews_layout = QHBoxLayout(self._previews_wrap)
        self._previews_layout.setContentsMargins(0, 0, 0, 0)
        self._previews_layout.setSpacing(16)
        self._source_card = self._preview_card("Исходный документ", self._source_scroll)
        self._revised_card = self._preview_card("Исправленный документ", self._revised_scroll)
        self._previews_layout.addWidget(self._source_card, 1)
        self._previews_layout.addWidget(self._revised_card, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._title)
        layout.addWidget(self._subtitle)
        layout.addWidget(self._summary)
        layout.addLayout(actions)
        layout.addWidget(self._changes_wrap)
        layout.addWidget(self._previews_wrap, 1)

    def set_result(self, result: RegulationRevisionResult) -> None:
        self._result = result
        self._pdf_download.setVisible(bool(result.pdf_download_url))
        changed_pages = {item.page for item in result.diff_blocks if item.page}
        self._render_change_nav()
        if result.source_preview_pages and result.revised_preview_pages and self._api is not None:
            self._render_pages(
                self._source_pages,
                result.source_preview_pages,
                result.source_preview_html,
                changed_pages,
                self._source_page_widgets,
            )
            self._render_pages(
                self._revised_pages,
                result.revised_preview_pages,
                result.revised_preview_html,
                changed_pages,
                self._revised_page_widgets,
            )
        else:
            self._render_html_fallback(self._source_pages, result.source_preview_html, "Исходный preview недоступен.")
            self._render_html_fallback(self._revised_pages, result.revised_preview_html, "Исправленный preview недоступен.")
        changed = len([item for item in result.diff_blocks if item.status == "changed"])
        self._summary.setText(f"{result.message}\nИзменённых блоков: {changed}")
        if changed_pages:
            QTimer.singleShot(0, lambda page=min(changed_pages): self._scroll_to_page(page))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        for widgets in (self._source_page_widgets, self._revised_page_widgets):
            for widget in widgets.values():
                widget.updateGeometry()

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

    def _rebuild_preview_layout(self, *, force: bool = False) -> None:
        if self._result is None:
            return
        if not force and self._previews_layout.count():
            return
        if not self._previews_layout.count():
            self._previews_layout.addWidget(self._source_card, 1)
            self._previews_layout.addWidget(self._revised_card, 1)

    @staticmethod
    def _page_scroll_area() -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: #F5F7F7; border: none; }")
        return scroll

    def _render_change_nav(self) -> None:
        _clear_layout(self._changes_layout)
        if self._result is None or not self._result.diff_blocks:
            self._changes_wrap.setVisible(False)
            return
        self._changes_wrap.setVisible(True)
        label = QLabel("Изменения:")
        label.setFont(app_font(12, QFont.Weight.DemiBold))
        label.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._changes_layout.addWidget(label)
        for index, diff in enumerate(self._result.diff_blocks, start=1):
            title = f"{index}. стр. {diff.page or '-'}"
            if diff.section:
                title = f"{title} · {diff.section[:34]}"
            btn = QPushButton(title)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(_diff_tooltip(diff.before, diff.after))
            btn.setStyleSheet(_secondary_button_qss())
            btn.clicked.connect(lambda _checked=False, page=diff.page: self._scroll_to_page(page))
            self._changes_layout.addWidget(btn)
        self._changes_layout.addStretch(1)

    def _render_pages(
        self,
        layout: QVBoxLayout,
        pages: list[RevisionPreviewPage],
        fallback_html: str,
        changed_pages: set[int],
        page_widgets: dict[int, QWidget],
    ) -> None:
        _clear_layout(layout)
        page_widgets.clear()
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
            page_frame = self._page_frame(page.page, pixmap, changed=page.page in changed_pages)
            page_widgets[page.page] = page_frame
            layout.addWidget(page_frame)
            rendered += 1
        if not rendered:
            self._render_html_fallback(layout, fallback_html, "Preview страниц недоступен.")
        else:
            layout.addStretch(1)

    def _page_frame(self, page_no: int, pixmap: QPixmap, *, changed: bool) -> QWidget:
        frame = QFrame()
        frame.setObjectName("ChangedPage" if changed else "Page")
        frame.setStyleSheet(
            """
            QFrame#Page {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.10);
                border-radius: 10px;
            }
            QFrame#ChangedPage {
                background: #FFFFFF;
                border: 2px solid rgba(8,116,95,0.75);
                border-radius: 10px;
            }
            """
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        header = QLabel(f"Страница {page_no}" + (" · изменено" if changed else ""))
        header.setFont(app_font(11, QFont.Weight.DemiBold))
        header.setStyleSheet("color: #08745F; background: transparent;" if changed else "color: #53625E; background: transparent;")
        image = PageImageLabel()
        image.setStyleSheet("background: #FFFFFF;")
        image.set_source_pixmap(pixmap)
        layout.addWidget(header)
        layout.addWidget(image)
        return frame

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

    def _scroll_to_page(self, page: int) -> None:
        if not page:
            return
        for scroll, widgets in (
            (self._source_scroll, self._source_page_widgets),
            (self._revised_scroll, self._revised_page_widgets),
        ):
            widget = widgets.get(page)
            if widget is None:
                continue
            scroll.verticalScrollBar().setValue(max(0, widget.y() - 12))


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


def _detach_layout(layout: QHBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)


def _diff_tooltip(before: str, after: str) -> str:
    before_text = _short_text(before)
    after_text = _short_text(after)
    return f"Было: {before_text}\nСтало: {after_text}"


def _short_text(text: str, limit: int = 180) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else f"{clean[:limit - 3]}..."


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
