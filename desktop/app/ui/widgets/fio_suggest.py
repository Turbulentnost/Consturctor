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

_ALL_KEY = ""
_MAX_VISIBLE_ROWS = 5
_ROW_HEIGHT = 40
_POPUP_MARGINS = 8
_MAX_ITEMS = 200
_WINDOW_EDGE_PAD = 12


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
        self._list.setUniformItemSizes(True)
        self._list.setStyleSheet(
            """
            QListWidget {
                background: transparent;
                color: #f5f7f6;
                border: none;
                outline: none;
                padding: 2px;
            }
            QListWidget::item {
                height: 36px;
                padding: 0 12px;
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
        lay.setSpacing(0)
        lay.addWidget(self._list)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(180)
        self._timer.timeout.connect(self._reload_suggestions)

        self.textEdited.connect(self._on_text_edited)
        self._suggestions_ready.connect(self._apply_async_suggestions)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        try:
            popup_visible = self._popup.isVisible()
            list_viewport = self._list.viewport()
        except RuntimeError:
            return False
        if popup_visible and event.type() == QEvent.Type.Wheel and obj in (
            self._popup,
            self._list,
            list_viewport,
        ):
            QApplication.sendEvent(list_viewport, event)
            return True
        return super().eventFilter(obj, event)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        self._open_suggestions()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        if not self._popup.isVisible():
            self._open_suggestions()

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
        self.hide_suggestions()
        super().hideEvent(event)

    def hide_suggestions(self) -> None:
        """Force-close the overlay (login success, page switch, etc.)."""
        self._timer.stop()
        self._request_token = ""
        self._hide_popup()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if self._popup.isVisible():
            self._position_popup()

    def _on_text_edited(self, _text: str) -> None:
        # Optimistic local filter (may be incomplete — catalog is only first N names).
        if _ALL_KEY in self._cache:
            self._apply_filtered_view(allow_empty=False)
            self._show_popup()
        self._timer.start()

    def _open_suggestions(self) -> None:
        query = self.text().strip()
        if not query and _ALL_KEY in self._cache:
            self._populate(self._cache[_ALL_KEY])
            self._show_popup()
            return
        if query and query.lower() in self._cache:
            self._populate(self._cache[query.lower()])
            self._show_popup()
            return
        if query and _ALL_KEY in self._cache:
            self._apply_filtered_view(allow_empty=False)
            self._show_popup()
        self._reload_suggestions()

    def _reload_suggestions(self) -> None:
        if self._suppress_fetch or not self.isVisible() or not self.isEnabled():
            return

        query = self.text().strip()
        key = query.lower()

        if key in self._cache:
            self._populate(self._cache[key])
            self._show_popup()
            return

        # Empty query → browse catalog; non-empty → server search (needed because
        # the empty catalog is only TOP N alphabetically and may miss the target FIO).
        self._request_token = key
        if not self._popup.isVisible() or self._list.count() == 0:
            self._populate_message("Загружаем список…")
            self._show_popup()
        Thread(target=self._fetch_in_background, args=(query, key), daemon=True).start()

    def _fetch_in_background(self, query: str, key: str) -> None:
        try:
            items = self._fetch(query)
        except Exception as exc:
            message = str(getattr(exc, "message", "") or exc).strip() or "Не удалось загрузить список"
            self._suggestions_ready.emit(key, {"error": message})
            return
        self._suggestions_ready.emit(key, items)

    def _apply_async_suggestions(self, key: str, items_obj: object) -> None:
        if isinstance(items_obj, dict) and items_obj.get("error"):
            if key != self._request_token:
                return
            self._populate_message(str(items_obj["error"]))
            self._show_popup()
            return
        items = [str(x) for x in (items_obj or [])]
        if key:
            items = [name for name in items if self._matches_query(name, key)]
        self._cache[key] = items
        if key != self._request_token:
            return
        if not self.isVisible() or not self.isEnabled():
            self._hide_popup()
            return
        if not items:
            self._populate_message("Ничего не найдено")
        else:
            self._populate(items)
        self._show_popup()

    def _apply_filtered_view(self, *, allow_empty: bool = True) -> None:
        catalog = self._cache.get(_ALL_KEY, [])
        query = self.text().strip().lower()
        if not query:
            matched = catalog
        else:
            matched = [name for name in catalog if self._matches_query(name, query)]
        if not matched:
            if allow_empty:
                self._populate_message("Ничего не найдено")
            # else keep current list until server responds
            return
        self._populate(matched)

    @staticmethod
    def _matches_query(name: str, query: str) -> bool:
        lowered = name.casefold()
        q = query.casefold()
        if lowered.startswith(q):
            return True
        return any(part.startswith(q) for part in lowered.split())

    def _populate_message(self, text: str) -> None:
        self._list.clear()
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        self._list.addItem(item)
        self._list.setCurrentRow(-1)

    def _populate(self, items: list[str]) -> None:
        self._list.clear()
        for value in items[:_MAX_ITEMS]:
            self._list.addItem(QListWidgetItem(value))
        self._list.setCurrentRow(-1)

    def _is_message_list(self) -> bool:
        if self._list.count() != 1:
            return False
        item = self._list.item(0)
        return item is not None and not (item.flags() & Qt.ItemFlag.ItemIsSelectable)

    def _desired_height(self) -> int:
        count = self._list.count()
        if count == 0:
            return 0
        if self._is_message_list():
            return _POPUP_MARGINS + _ROW_HEIGHT
        visible_rows = min(count, _MAX_VISIBLE_ROWS)
        return _POPUP_MARGINS + visible_rows * _ROW_HEIGHT

    def _position_popup(self) -> None:
        width = max(self.width(), 320)
        height = self._desired_height()
        if height <= 0:
            return

        top = self.window()
        if top is None:
            return
        if self._popup.parentWidget() is not top:
            self._popup.setParent(top)
            self._popup.setWindowFlags(Qt.WindowType.Widget)

        below = self.mapTo(top, QPoint(0, self.height() + 6))
        above = self.mapTo(top, QPoint(0, 0))
        space_below = top.height() - below.y() - _WINDOW_EDGE_PAD
        space_above = above.y() - _WINDOW_EDGE_PAD

        if space_below >= min(height, _POPUP_MARGINS + _ROW_HEIGHT * 3) or space_below >= space_above:
            height = min(height, max(_POPUP_MARGINS + _ROW_HEIGHT, space_below))
            pos = below
        else:
            height = min(height, max(_POPUP_MARGINS + _ROW_HEIGHT, space_above))
            pos = QPoint(above.x(), above.y() - height - 6)

        self._popup.setFixedSize(width, height)
        self._popup.move(pos)
        self._list.setMinimumHeight(0)
        self._list.setMaximumHeight(16777215)
        self._list.setFixedHeight(max(_ROW_HEIGHT, height - _POPUP_MARGINS))

    def _show_popup(self) -> None:
        if self._list.count() == 0 or not self.isVisible() or not self.isEnabled():
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
