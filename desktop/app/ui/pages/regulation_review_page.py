from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
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
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, SIDEBAR_MIDDLE, app_font


class RegulationReviewPage(QWidget):
    back_requested = Signal()
    continue_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._summary = QVBoxLayout()
        self._content = QVBoxLayout()

        title = QLabel("Проверка регламента")
        title.setFont(app_font(30, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        subtitle = QLabel("Проверьте распознанный текст, таблицы и структуру документа")
        subtitle.setFont(app_font(14))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        left = QFrame()
        left.setObjectName("ReviewSide")
        left.setFixedWidth(290)
        left.setStyleSheet(_panel_qss())
        left_layout = QVBoxLayout(left)
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
        scroll.setStyleSheet("background: transparent; border: none;")

        right = QFrame()
        right.setObjectName("ReviewMain")
        right.setStyleSheet(_panel_qss())
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(18, 18, 18, 18)
        right_layout.addWidget(scroll)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(18)
        body.addWidget(left, 0)
        body.addWidget(right, 1)

        back = QPushButton("Назад")
        back.setFixedHeight(42)
        back.setCursor(Qt.CursorShape.PointingHandCursor)
        back.setFont(app_font(13, QFont.Weight.DemiBold))
        back.setStyleSheet(_secondary_button_qss())
        back.clicked.connect(self.back_requested.emit)

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
        root.addLayout(body, 1)
        root.addLayout(actions)

    def set_result(self, result: RegulationParseResult) -> None:
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


def _table_widget(fragment: RegulationFragment) -> QTableWidget:
    table_data = fragment.table
    assert table_data is not None
    rows = table_data.rows
    headers = table_data.headers
    column_count = max(len(headers), *(len(row) for row in rows), 1)
    table = QTableWidget(max(len(rows), 1), column_count)
    table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    table.setHorizontalHeaderLabels(headers + [""] * (column_count - len(headers)))
    table.verticalHeader().hide()
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
    table.setAlternatingRowColors(True)
    table.setStyleSheet(
        """
        QTableWidget {
            background: #FFFFFF;
            border: 1px solid rgba(16,24,23,0.08);
            gridline-color: rgba(16,24,23,0.10);
        }
        QHeaderView::section {
            background: #EEF7F3;
            color: #101817;
            border: none;
            padding: 6px;
        }
        """
    )
    source_rows = rows or [[""] * column_count]
    for r, row in enumerate(source_rows):
        for c in range(column_count):
            table.setItem(r, c, QTableWidgetItem(row[c] if c < len(row) else ""))
    table.resizeColumnsToContents()
    table.setFixedHeight(min(240, 34 + 32 * max(1, len(source_rows))))
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
