from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.storage.session_log import (
    HISTORY_LABELS,
    format_history_body,
    preview_text,
    should_collapse_entry,
)
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font
from app.ui.widgets.markdown_body import MarkdownBody

_KIND_STYLE = {
    "user": ("#06483D", "#EAF7F3", "rgba(8,116,95,0.22)"),
    "agent": ("#101817", "#FFFFFF", "rgba(16,24,23,0.10)"),
    "thinking": ("#6B7773", "#F6F8F7", "rgba(16,24,23,0.08)"),
    "tool": ("#0A5C48", "#F3FAF7", "rgba(8,116,95,0.18)"),
    "system": ("#6B7773", "#F7F8F7", "rgba(16,24,23,0.08)"),
    "error": ("#9B1C1C", "#FFF4F4", "rgba(155,28,28,0.22)"),
}

_BLOCK_QSS = """
QFrame#HistoryBlock {{
    background: {bg};
    border: 1px solid {border};
    border-radius: 12px;
}}
QFrame#HistoryBlockHeader {{
    background: transparent;
    border: none;
}}
QFrame#HistoryBlockHeader:hover {{
    background: rgba(16,24,23,0.04);
    border-radius: 10px;
}}
"""

_BODY_EDIT_QSS = """
QPlainTextEdit {
    background: transparent;
    border: none;
    color: #101817;
    padding: 0;
}
"""


class _Header(QFrame):
    def __init__(self, parent: "_HistoryBlock") -> None:
        super().__init__(parent)
        self._block = parent
        self.setObjectName("HistoryBlockHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._block.toggle()
        super().mousePressEvent(event)


class _HistoryBlock(QFrame):
    def __init__(self, kind: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("HistoryBlock")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._kind = kind
        self._raw = text
        self._body_text = format_history_body(text)
        self._expanded = not should_collapse_entry(kind, self._body_text)
        fg, bg, border = _KIND_STYLE.get(kind, _KIND_STYLE["agent"])
        self.setStyleSheet(_BLOCK_QSS.format(bg=bg, border=border))

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        header = _Header(self)
        row = QHBoxLayout(header)
        row.setContentsMargins(2, 0, 2, 0)
        row.setSpacing(8)

        self._chevron = QLabel("▼" if self._expanded else "▶")
        self._chevron.setFixedWidth(14)
        self._chevron.setFont(app_font(11, QFont.Weight.DemiBold))
        self._chevron.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        title = QLabel(HISTORY_LABELS.get(kind, kind))
        title.setFont(app_font(13, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {fg}; background: transparent;")

        row.addWidget(self._chevron, 0, Qt.AlignmentFlag.AlignTop)
        row.addWidget(title, 0, Qt.AlignmentFlag.AlignTop)
        row.addStretch(1)
        root.addWidget(header)

        self._preview = QLabel(preview_text(self._body_text))
        self._preview.setWordWrap(True)
        self._preview.setFont(app_font(12))
        self._preview.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self._preview)

        self._body = self._make_body()
        root.addWidget(self._body)
        self._apply_expanded()

    def toggle(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded()

    def _apply_expanded(self) -> None:
        self._chevron.setText("▼" if self._expanded else "▶")
        self._preview.setVisible(not self._expanded)
        self._body.setVisible(self._expanded)

    def _make_body(self) -> QWidget:
        if self._use_code_body():
            edit = QPlainTextEdit()
            edit.setReadOnly(True)
            edit.setFrameShape(QFrame.Shape.NoFrame)
            edit.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
            edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            edit.setFont(app_font(12))
            edit.setPlainText(self._body_text)
            edit.setStyleSheet(_BODY_EDIT_QSS)
            edit.setMaximumHeight(260)
            edit.setMinimumHeight(72)
            edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
            return edit
        if self._kind == "agent":
            return MarkdownBody(self._body_text, font_size=13, weight=QFont.Weight.Medium)
        label = QLabel(self._body_text)
        label.setWordWrap(True)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setFont(app_font(13))
        color = "#9B1C1C" if self._kind == "error" else MAIN_TEXT.name()
        if self._kind in {"thinking", "system"}:
            color = COLOR_CONTENT_MUTED.name()
        label.setStyleSheet(f"color: {color}; background: transparent;")
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        return label

    def _use_code_body(self) -> bool:
        if self._kind == "tool":
            return True
        stripped = self._body_text.lstrip()
        return stripped.startswith("{") or stripped.startswith("[") or "\n{" in self._body_text[:80]


class HistoryList(QScrollArea):
    def __init__(
        self,
        entries: list[tuple[str, str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(280)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        host = QWidget()
        host.setStyleSheet("background: transparent;")
        host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)
        for kind, text in entries:
            body = (text or "").strip()
            if not kind or not body:
                continue
            layout.addWidget(_HistoryBlock(kind, body))
        layout.addStretch(1)
        self.setWidget(host)
