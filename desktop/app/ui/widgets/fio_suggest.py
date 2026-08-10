from __future__ import annotations

from collections.abc import Callable
from threading import Thread

from PySide6.QtCore import QEvent, QPoint, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from app.ui.theme import app_font

_MAX_VISIBLE_ROWS = 8
_MIN_LIST_HEIGHT = 200


class FioSuggestEdit(QLineEdit):
    """FIO field with click-to-open suggestions; never auto-fills while typing."""

    _suggestions_ready = Signal(str, object)

    def __init__(
        self,
        fetch_suggestions: Callable[[str], list[str]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._fetch = fetch_suggestions
        self._suppress_fetch = False
        self._cache: dict[str, list[str]] = {}
        self._request_token = ""

        self.setPlaceholderText("Начните вводить ФИО…")
        self.setFont(app_font(13))

        # Plain child overlay, not a native Popup. Native Popup steals focus on
        # Windows, which breaks typing and can disappear immediately.
        self._popup = QFrame(None)
        self._popup.hide()
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popup.setStyleSheet(
            """
            QFrame {
                background: #062e24;
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 14px;
            }
            """
        )
        self._list = QListWidget(self._popup)
        self._list.setFont(app_font(13))
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setStyleSheet(
            """
            QListWidget {
                background: transparent;
                color: #f5f7f6;
                border: none;
                outline: none;
                padding: 4px;
            }
            QListWidget::item {
                padding: 10px 14px;
                border-radius: 10px;
            }
            QListWidget::item:hover,
            QListWidget::item:selected {
                background: #0a4a38;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 2px 4px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.25);
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.installEventFilter(self)
        self._popup.installEventFilter(self)

        lay = QVBoxLayout(self._popup)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self._list)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._reload_suggestions)

        self.textEdited.connect(self._on_text_edited)
        self._suggestions_ready.connect(self._apply_async_suggestions)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (
            self._popup.isVisible()
            and event.type() == QEvent.Type.Wheel
            and obj in (self._popup, self._list, self._list.viewport())
        ):
            QApplication.sendEvent(self._list.viewport(), event)
            return True
        return super().eventFilter(obj, event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._show_hint_or_cached()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        if not self._popup.isVisible():
            self._show_hint_or_cached()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()
        if self._popup.isVisible() and self._list.count() > 0:
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                row = self._list.currentRow()
                if key == Qt.Key.Key_Down:
                    row = 0 if row < 0 else min(row + 1, self._list.count() - 1)
                else:
                    row = self._list.count() - 1 if row < 0 else max(row - 1, 0)
                self._list.setCurrentRow(row)
                self._list.scrollToItem(self._list.currentItem())
                event.accept()
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self._list.currentItem():
                self._apply_item(self._list.currentItem())
                event.accept()
                return
            if key == Qt.Key.Key_Escape:
                self._hide_popup()
                event.accept()
                return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._hide_popup()
        super().hideEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if self._popup.isVisible():
            self._position_popup()

    def _on_text_edited(self, _text: str) -> None:
        self._timer.start()

    def _show_hint_or_cached(self) -> None:
        query = self.text().strip()
        key = query.lower()
        if len(query) < 2:
            self._populate_message("Введите минимум 2 символа")
            self._show_popup()
            return
        if key in self._cache:
            self._populate(self._cache[key])
            self._show_popup()
            return
        self._reload_suggestions()

    def _reload_suggestions(self) -> None:
        if self._suppress_fetch:
            return
        query = self.text().strip()
        if len(query) < 2:
            self._populate_message("Введите минимум 2 символа")
            self._show_popup()
            return

        key = query.lower()
        if key in self._cache:
            self._populate(self._cache[key])
            self._show_popup()
            return

        self._request_token = key
        self._populate_message("Ищем совпадения…")
        self._show_popup()
        Thread(target=self._fetch_in_background, args=(query, key), daemon=True).start()

    def _fetch_in_background(self, query: str, key: str) -> None:
        try:
            items = self._fetch(query)
        except Exception:
            items = []
        self._suggestions_ready.emit(key, items)

    def _apply_async_suggestions(self, key: str, items_obj: object) -> None:
        items = [str(x) for x in (items_obj or [])]
        self._cache[key] = items
        if key != self._request_token:
            return
        if not items:
            self._populate_message("Ничего не найдено")
        else:
            self._populate(items)
        self._show_popup()

    def _populate_message(self, text: str) -> None:
        self._list.clear()
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._list.addItem(item)
        self._list.setCurrentRow(-1)

    def _populate(self, items: list[str]) -> None:
        self._list.clear()
        for value in items[:40]:
            self._list.addItem(QListWidgetItem(value))
        self._list.setCurrentRow(-1)

    def _row_height(self) -> int:
        if self._list.count() > 0:
            hint = self._list.sizeHintForRow(0)
            if hint > 0:
                return max(hint, 44)
        return 44

    def _is_message_list(self) -> bool:
        if self._list.count() != 1:
            return False
        item = self._list.item(0)
        return item is not None and not (item.flags() & Qt.ItemFlag.ItemIsSelectable)

    def _popup_size(self) -> tuple[int, int]:
        width = max(self.width(), 320)
        count = self._list.count()
        if count == 0:
            return width, 0

        row_h = self._row_height()
        margins = 8

        if self._is_message_list():
            return width, margins + row_h

        visible_rows = min(count, _MAX_VISIBLE_ROWS)
        height = margins + visible_rows * row_h
        if count >= 3:
            height = max(height, _MIN_LIST_HEIGHT)
        return width, height

    def _position_popup(self) -> None:
        width, height = self._popup_size()
        if height <= 0:
            return
        top = self.window()
        if self._popup.parentWidget() is not top:
            self._popup.setParent(top)
            self._popup.setWindowFlags(Qt.WindowType.Widget)
        self._popup.setFixedSize(width, height)
        pos = self.mapTo(top, QPoint(0, self.height() + 6))
        self._popup.move(pos)

    def _show_popup(self) -> None:
        if self._list.count() == 0:
            self._hide_popup()
            return
        self._position_popup()
        self._popup.show()
        self._popup.raise_()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _hide_popup(self) -> None:
        self._popup.hide()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._apply_item(item)

    def _apply_item(self, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        self._suppress_fetch = True
        self.setText(item.text())
        self._suppress_fetch = False
        self._hide_popup()
        self.setCursorPosition(len(self.text()))
        self.setFocus(Qt.FocusReason.MouseFocusReason)
