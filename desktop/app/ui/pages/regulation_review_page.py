from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.api_client import RegulationFragment, RegulationParseResult
from app.ui.theme import (
    COLOR_CONTENT_MUTED,
    MAIN_TEXT,
    SIDEBAR_MIDDLE,
    app_font,
    scroll_bar_qss,
)


class RegulationReviewPage(QWidget):
    back_requested = Signal()
    continue_requested = Signal()
    fullscreen_changed = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fullscreen = False
        self._summary = QVBoxLayout()
        self._content = QVBoxLayout()

        title = QLabel("Проверка регламента")
        title.setFont(app_font(30, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        subtitle = QLabel("Проверьте распознанный текст, таблицы и структуру документа")
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        self._left = QFrame()
        self._left.setObjectName("ReviewSide")
        self._left.setFixedWidth(290)
        self._left.setStyleSheet(_panel_qss())
        left_layout = QVBoxLayout(self._left)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(10)
        left_layout.addLayout(self._summary)
        left_layout.addStretch(1)

        scroll_content = QWidget()
        scroll_content.setStyleSheet("background: transparent;")
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(12)
        scroll_content.setLayout(self._content)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(scroll_content)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            + scroll_bar_qss()
        )
        scroll.verticalScrollBar().setStyleSheet(scroll_bar_qss())
        scroll.horizontalScrollBar().setStyleSheet(scroll_bar_qss())

        right = QFrame()
        right.setObjectName("ReviewMain")
        right.setStyleSheet(_panel_qss())
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.addWidget(scroll)

        self._body = QHBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(18)
        self._body.addWidget(self._left, 0)
        self._body.addWidget(right, 1)

        back = QPushButton("Назад")
        back.setFixedHeight(42)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFont(app_font(13, QFont.Weight.DemiBold))
        back.setStyleSheet(_secondary_button_qss())
        back.clicked.connect(self._on_back)

        next_btn = QPushButton("Продолжить")
        next_btn.setFixedHeight(42)
        next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        next_btn.setFont(app_font(13, QFont.Weight.DemiBold))
        next_btn.setStyleSheet(_primary_button_qss())
        next_btn.clicked.connect(self.continue_requested.emit)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(back)
        actions.addWidget(next_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addSpacing(12)
        root.addLayout(self._body, 1)
        root.addLayout(actions)

    def is_fullscreen(self) -> bool:
        return self._fullscreen

    def set_fullscreen(self, enabled: bool) -> None:
        if self._fullscreen == enabled:
            return
        self._fullscreen = enabled
        self._left.setVisible(not enabled)
        self.fullscreen_changed.emit(enabled)

    def toggle_fullscreen(self) -> None:
        self.set_fullscreen(not self._fullscreen)

    def set_result(self, result: RegulationParseResult) -> None:
        self.set_fullscreen(False)
        _clear_layout(self._summary)
        _clear_layout(self._content)
        self._summary.addWidget(_metric("Файл", result.file_name))
        self._summary.addWidget(_metric("Страниц", str(result.page_count)))
        self._summary.addWidget(_metric("Таблиц", str(result.table_count)))
        self._summary.addWidget(_metric("Разделов", str(result.section_count)))
        self._summary.addWidget(_metric("Качество", f"{result.recognition_quality * 100:.0f}%"))
        self._summary.addWidget(_metric("OCR", "скан PDF" if result.is_scan else "не требовался"))

        sections_title = QLabel("Заголовки")
        sections_title.setFont(app_font(14, QFont.Weight.DemiBold))
        sections_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._summary.addSpacing(8)
        self._summary.addWidget(sections_title)
        if result.sections:
            for section in result.sections:
                item = QLabel(section)
                item.setWordWrap(True)
                item.setFont(app_font(12))
                item.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
                self._summary.addWidget(item)
        else:
            empty = QLabel("Заголовки не найдены")
            empty.setFont(app_font(12))
            empty.setStyleSheet("color: #9AA6A1; background: transparent;")
            self._summary.addWidget(empty)

        for fragment in result.fragments:
            self._content.addWidget(_fragment_widget(fragment))
        self._content.addStretch(1)

    def _on_back(self) -> None:
        if self._fullscreen:
            self.set_fullscreen(False)
        self.back_requested.emit()


def _fragment_widget(fragment: RegulationFragment) -> QWidget:
    frame = QFrame()
    frame.setObjectName("Fragment")
    frame.setStyleSheet(
        """
        QFrame#Fragment {
            background: #FFFFFF;
            border: 1px solid rgba(16,24,23,0.10);
            border-radius: 14px;
        }
        """
    )
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(8)

    meta = QLabel(
        f"Стр. {fragment.page} · {fragment.section or 'без раздела'} · "
        f"{fragment.ocr_confidence * 100:.0f}%"
    )
    meta.setFont(app_font(11, QFont.Weight.DemiBold))
    meta.setStyleSheet(f"color: {SIDEBAR_MIDDLE.name()}; background: transparent;")
    meta.setWordWrap(True)
    layout.addWidget(meta)

    if fragment.kind == "table" and fragment.table is not None:
        layout.addWidget(_table_widget(fragment))
    else:
        text = QLabel(fragment.text or "Пустой фрагмент")
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        text.setFont(app_font(13))
        text.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        layout.addWidget(text)
    return frame


class _ReviewTable(QTableWidget):
    """Table that fills card width when narrow and scrolls when wider/taller."""

    _MAX_COL = 420
    _MIN_COL = 72
    _MAX_HEIGHT = 320

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.verticalHeader().hide()
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setAlternatingRowColors(True)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setShowGrid(True)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(False)
        self.setStyleSheet(
            """
            QTableWidget {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.08);
                border-radius: 10px;
                gridline-color: rgba(16,24,23,0.10);
            }
            QHeaderView::section {
                background: #EEF7F3;
                color: #101817;
                border: none;
                border-right: 1px solid rgba(16,24,23,0.08);
                border-bottom: 1px solid rgba(16,24,23,0.10);
                padding: 8px 10px;
            }
            QTableWidget::item {
                padding: 8px 10px;
            }
            """
            + scroll_bar_qss()
        )
        self.horizontalScrollBar().setStyleSheet(scroll_bar_qss())
        self.verticalScrollBar().setStyleSheet(scroll_bar_qss())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.fit_columns()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.fit_columns()
        self._update_height()

    def fit_columns(self) -> None:
        cols = self.columnCount()
        if cols <= 0:
            return
        for i in range(cols):
            self.resizeColumnToContents(i)
            width = self.columnWidth(i)
            self.setColumnWidth(i, max(self._MIN_COL, min(width + 8, self._MAX_COL)))

        available = self.viewport().width()
        if available <= 0:
            return
        total = sum(self.columnWidth(i) for i in range(cols))
        if total >= available:
            return

        # Stretch columns to fill card width so short tables don't look clipped.
        leftover = available - total
        base = leftover // cols
        rem = leftover - base * cols
        for i in range(cols):
            add = base + (1 if i >= cols - rem else 0)
            self.setColumnWidth(i, self.columnWidth(i) + add)

    def _update_height(self) -> None:
        rows = max(self.rowCount(), 1)
        header_h = self.horizontalHeader().height() if not self.horizontalHeader().isHidden() else 0
        frame = self.frameWidth() * 2
        row_h = max(self.verticalHeader().defaultSectionSize(), 34)
        content_h = header_h + row_h * rows + frame + 2
        self.setFixedHeight(min(self._MAX_HEIGHT, max(96, content_h)))


def _table_widget(fragment: RegulationFragment) -> QTableWidget:
    table_data = fragment.table
    assert table_data is not None
    rows = table_data.rows
    headers = table_data.headers
    column_count = max(len(headers), *(len(row) for row in rows), 1) if rows or headers else 1
    table = _ReviewTable()
    source_rows = rows or [[""] * column_count]
    table.setRowCount(len(source_rows))
    table.setColumnCount(column_count)

    has_headers = any(str(h).strip() for h in headers)
    if has_headers:
        labels = [str(h) for h in headers] + [""] * (column_count - len(headers))
        table.setHorizontalHeaderLabels(labels)
    else:
        table.horizontalHeader().hide()

    for r, row in enumerate(source_rows):
        for c in range(column_count):
            item = QTableWidgetItem(row[c] if c < len(row) else "")
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            table.setItem(r, c, item)
        table.setRowHeight(r, max(34, table.rowHeight(r)))

    table.fit_columns()
    table._update_height()
    return table


def _metric(label: str, value: str) -> QWidget:
    box = QFrame()
    box.setStyleSheet("background: #F4F7F6; border-radius: 10px;")
    layout = QVBoxLayout(box)
    layout.setContentsMargins(10, 8, 10, 8)
    layout.setSpacing(2)
    title = QLabel(label)
    title.setFont(app_font(10, QFont.Weight.DemiBold))
    title.setStyleSheet("color: #9AA6A1; background: transparent;")
    body = QLabel(value)
    body.setFont(app_font(13, QFont.Weight.DemiBold))
    body.setWordWrap(True)
    body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
    layout.addWidget(title)
    layout.addWidget(body)
    return box


def _clear_layout(layout: QVBoxLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)


def _panel_qss() -> str:
    return """
    QFrame#ReviewSide, QFrame#ReviewMain {
        background: #FFFFFF;
        border: 1px solid rgba(16,24,23,0.10);
        border-radius: 18px;
    }
    """


def _primary_button_qss() -> str:
    return """
    QPushButton {
        background: #06483D;
        color: #F7FBFA;
        border: none;
        border-radius: 21px;
        padding: 0 22px;
    }
    QPushButton:hover { background: #08745F; }
    """


def _secondary_button_qss() -> str:
    return """
    QPushButton {
        background: #EEF7F3;
        color: #06483D;
        border: none;
        border-radius: 21px;
        padding: 0 22px;
    }
    QPushButton:hover { background: #DFF5EC; }
    """
