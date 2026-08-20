from __future__ import annotations

import json
from typing import Any

from PySide6.QtCore import Qt, QSize, Signal
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font
from app.ui.widgets.markdown_body import MarkdownBody

_LONG_PREVIEW = 360
_TOOL_DETAIL_MAX_H = 220

_COLLAPSE_HEADER = """
QFrame#cursorcollapse {
    background: transparent;
    border: none;
    border-radius: 8px;
}
QFrame#cursorcollapse:hover {
    background: rgba(16,24,23,0.05);
}
"""

_TOOL_HEADER = """
QFrame#cursorcollapse {
    background: #F1F4F3;
    border: none;
    border-radius: 10px;
}
QFrame#cursorcollapse:hover {
    background: #E8EEEC;
}
"""

_DETAIL_BOX = """
QFrame#cursordetail {
    background: #F6F8F7;
    border: 1px solid rgba(16,24,23,0.06);
    border-radius: 10px;
}
"""

_ACTION_BTN = """
QPushButton {
    background: #F1F5F3; color: #06483D; border: none;
    border-radius: 12px; padding: 8px 14px; text-align: left;
}
QPushButton:hover { background: #E4EDE9; }
"""

_TOGGLE_LINK = """
QLabel#cursortoggle {
    color: #6B7773;
    background: transparent;
}
QLabel#cursortoggle:hover {
    color: #08745F;
}
"""


def resolve_feed_kind(*, role: str = "", title: str = "", kind: str = "") -> str:
    if kind:
        return kind
    if (role or "").strip().casefold() == "user" or (title or "").strip().casefold() in {"вы", "you"}:
        return "user"
    folded = (title or "").strip().casefold()
    if folded in {"план", "шаги плана"}:
        return "plan"
    if folded in {"результат", "результат тестового прогона"}:
        return "result"
    if folded == "ошибка":
        return "error"
    if folded in {"thinking", "планирование"}:
        return "thinking"
    if folded in {"инструмент", "tool"} or folded.startswith("инструмент:"):
        return "tool"
    if folded in {"предупреждение", "система"}:
        return "system"
    return "agent"


_COLLECTION_LABELS = {
    "projects": "проектов",
    "users": "пользователей",
    "items": "записей",
    "results": "результатов",
    "documents": "документов",
    "cards": "карточек",
    "files": "файлов",
    "messages": "писем",
    "events": "событий",
}


def format_collection_result(result: Any) -> str | None:
    if not isinstance(result, dict):
        return None
    for key, label in _COLLECTION_LABELS.items():
        value = result.get(key)
        if not isinstance(value, list):
            continue
        count = result.get("count", len(value))
        lines = [f"Готово · {count} {label}"]
        for row in value[:15]:
            title = _row_title(row)
            if title:
                lines.append(f"• {title}")
        extra = len(value) - 15
        if extra > 0:
            lines.append(f"… ещё {extra}")
        return "\n".join(lines)
    return None


def format_tool_detail(arguments: Any = None, result: Any = None) -> str:
    """Только выход инструмента. Вход (arguments) в ленту не кладём."""
    _ = arguments
    friendly = format_collection_result(result)
    if friendly:
        return friendly
    if result not in (None, {}, ""):
        return _pretty(result)
    return "Ожидание результата…"


def _row_title(row: Any) -> str:
    if isinstance(row, str):
        return row.strip()
    if not isinstance(row, dict):
        return str(row).strip()
    for key in ("name", "title", "fio", "email", "file", "path", "id", "projectName"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _pretty(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except Exception:
        return str(value)


def _preview_text(text: str, limit: int = _LONG_PREVIEW) -> str:
    cleaned = (text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    cut = cleaned[:limit].rsplit(" ", 1)[0].rstrip()
    return (cut or cleaned[:limit]) + "…"


class _WrapLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def _available_width(self) -> int:
        w = self.width()
        if w >= 80:
            return w
        parent = self.parentWidget()
        while parent is not None:
            if parent.width() >= 80:
                return parent.width()
            parent = parent.parentWidget()
        return 420

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return max(super().heightForWidth(max(80, width)), 0)

    def sizeHint(self) -> QSize:  # noqa: N802
        w = self._available_width()
        return QSize(w, self.heightForWidth(w))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, 0)


class _CollapseHeader(QFrame):
    clicked = Signal()

    def __init__(
        self,
        title: str,
        expanded: bool,
        parent: QWidget | None = None,
        *,
        variant: str = "",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("cursorcollapse")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setStyleSheet(_TOOL_HEADER if variant == "tool" else _COLLAPSE_HEADER)
        row = QHBoxLayout(self)
        if variant == "tool":
            row.setContentsMargins(10, 6, 10, 6)
            self.setFixedHeight(36)
        else:
            row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(8)
        self._chevron = QLabel("▼" if expanded else "▶")
        self._chevron.setFixedWidth(14)
        self._chevron.setFont(app_font(11))
        self._chevron.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._title = QLabel(title)
        self._title.setFont(app_font(13, QFont.Weight.Medium))
        self._title.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._title.setWordWrap(True)
        row.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._title, 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def set_expanded(self, expanded: bool) -> None:
        self._chevron.setText("▼" if expanded else "▶")


class _ToggleLink(QLabel):
    clicked = Signal()

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("cursortoggle")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFont(app_font(12, QFont.Weight.Medium))
        self.setStyleSheet(_TOGGLE_LINK)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class CursorFeedItem(QFrame):
    """Plain Cursor-style feed row: no avatar, no timestamp, collapsible extras."""

    action_clicked = Signal(str)
    expand_toggled = Signal(str, bool)

    def __init__(
        self,
        *,
        kind: str,
        text: str = "",
        title: str = "",
        detail: str = "",
        action: str = "",
        action_key: str = "",
        event_key: str = "",
        expanded: bool = False,
        arguments: Any = None,
        result: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self._text = text or ""
        self._title = title or ""
        self._detail = detail or ""
        self._action = action
        self._action_key = action_key
        self._event_key = event_key
        self._expanded = expanded
        if kind == "tool" and not self._detail:
            self._detail = format_tool_detail(arguments, result)
        if not self._detail:
            self._detail = self._text
        self.setStyleSheet("background: transparent;")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._header: _CollapseHeader | None = None
        self._detail_frame: QFrame | None = None
        self._detail_label: _WrapLabel | None = None
        self._plain_label: QWidget | None = None
        self._preview: QWidget | None = None
        self._toggle: _ToggleLink | None = None
        self._build()

    def set_body_text(self, text: str) -> None:
        """Обновить текст без пересоздания виджета — иначе лента скачет."""
        self._text = text or ""
        self._detail = self._text
        if self._detail_label is not None:
            self._detail_label.setText(self._detail)
        if self._plain_label is not None:
            if hasattr(self._plain_label, "set_markdown"):
                self._plain_label.set_markdown(self._text)
            elif hasattr(self._plain_label, "setText"):
                self._plain_label.setText(self._text)

    def set_tool_detail(self, detail: str) -> None:
        """Обновить вывод инструмента, не трогая шапку и не пересобирая ленту."""
        body = (detail or "").strip() or self._detail
        self._text = body
        self._detail = body
        if self._detail_label is not None:
            self._detail_label.setText(body)
        if self._kind == "tool" and body and body not in {"Выполняется…", "Готово"}:
            self.set_expanded(True)

    def set_expanded(self, expanded: bool) -> None:
        if bool(self._expanded) == bool(expanded):
            return
        self._expanded = bool(expanded)
        if self._header is not None:
            self._header.set_expanded(self._expanded)
        if self._detail_frame is not None:
            self._detail_frame.setVisible(self._expanded)
        if self._preview is not None:
            self._preview.setVisible(not self._expanded)
        if self._toggle is not None:
            self._toggle.setText("Свернуть" if self._expanded else "Показать полностью")
        self.expand_toggled.emit(self._event_key, self._expanded)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 8)
        root.setSpacing(4)
        if self._kind in {"thinking", "plan", "tool", "result"}:
            self._build_collapsible(root)
        elif self._is_long_plain():
            self._build_long_plain(root)
        else:
            body = self._plain_body(self._text)
            self._plain_label = body
            root.addWidget(body)
        if self._action:
            btn = QPushButton(self._action)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(app_font(12, QFont.Weight.DemiBold))
            btn.setStyleSheet(_ACTION_BTN)
            btn.setFixedHeight(36)
            key = self._action_key
            btn.clicked.connect(lambda _=False, k=key: self.action_clicked.emit(k))
            root.addWidget(btn, 0, Qt.AlignmentFlag.AlignLeft)

    def _is_long_plain(self) -> bool:
        return self._kind in {"agent", "user", "system", "error"} and len((self._text or "").strip()) > _LONG_PREVIEW

    def _header_title(self) -> str:
        if self._title:
            return self._title
        if self._kind == "thinking":
            return "Thinking"
        if self._kind == "plan":
            return "План"
        if self._kind == "result":
            return "Результат"
        if self._kind == "tool":
            return "Инструмент"
        return "Подробнее"

    def _build_collapsible(self, root: QVBoxLayout) -> None:
        self._header = _CollapseHeader(
            self._header_title(),
            self._expanded,
            variant="tool" if self._kind == "tool" else "",
        )
        self._header.clicked.connect(self._toggle_expand)
        root.addWidget(self._header)
        if self._kind == "plan":
            preview = _preview_text(self._text or self._detail, limit=180)
            if preview:
                label = _WrapLabel(preview)
                label.setFont(app_font(13))
                label.setStyleSheet(
                    f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;"
                )
                self._preview = label
                self._preview.setVisible(not self._expanded)
                root.addWidget(self._preview)
        self._detail_frame = self._detail_box(self._detail)
        self._detail_frame.setVisible(self._expanded)
        root.addWidget(self._detail_frame)

    def _build_long_plain(self, root: QVBoxLayout) -> None:
        preview = _preview_text(self._text)
        self._preview = self._plain_body(preview)
        self._preview.setVisible(not self._expanded)
        self._detail_frame = self._plain_body(self._text)
        self._detail_frame.setVisible(self._expanded)
        self._toggle = _ToggleLink("Свернуть" if self._expanded else "Показать полностью")
        self._toggle.clicked.connect(self._toggle_expand)
        root.addWidget(self._preview)
        root.addWidget(self._detail_frame)
        root.addWidget(self._toggle, 0, Qt.AlignmentFlag.AlignLeft)

    def _plain_body(self, text: str) -> QWidget:
        if self._kind == "agent":
            return MarkdownBody(text, font_size=14, weight=QFont.Weight.Medium)
        color = MAIN_TEXT.name()
        weight = QFont.Weight.Medium
        if self._kind == "error":
            color = "#B00020"
        elif self._kind == "system":
            color = COLOR_CONTENT_MUTED.name()
        elif self._kind == "user":
            weight = QFont.Weight.DemiBold
        label = _WrapLabel(text)
        label.setFont(app_font(14, weight))
        label.setStyleSheet(f"color: {color}; background: transparent;")
        return label

    def _detail_box(self, text: str) -> QFrame:
        box = QFrame()
        box.setObjectName("cursordetail")
        box.setStyleSheet(_DETAIL_BOX)
        box.setMinimumWidth(0)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        lay = QVBoxLayout(box)
        lay.setContentsMargins(12, 8, 12, 8)
        body = _WrapLabel(text)
        body.setFont(app_font(12))
        body.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._detail_label = body
        if self._kind == "tool":
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setMaximumHeight(_TOOL_DETAIL_MAX_H)
            scroll.setWidget(body)
            scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
            scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            lay.addWidget(scroll)
        else:
            lay.addWidget(body)
        return box

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        if self._header is not None:
            self._header.set_expanded(self._expanded)
        if self._detail_frame is not None:
            self._detail_frame.setVisible(self._expanded)
        if self._preview is not None:
            self._preview.setVisible(not self._expanded)
        if self._toggle is not None:
            self._toggle.setText("Свернуть" if self._expanded else "Показать полностью")
        self.expand_toggled.emit(self._event_key, self._expanded)
