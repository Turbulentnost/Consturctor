from __future__ import annotations

import html
import re

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QSizePolicy, QTextBrowser

from app.ui.theme import MAIN_TEXT, app_font


_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
_HEADING = re.compile(r"^(#{1,3})\s+(.+)$")
_UL = re.compile(r"^[-*•]\s+(.+)$")
_OL = re.compile(r"^(\d+)[.)]\s+(.+)$")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")
_FENCE = re.compile(r"^```")


def markdown_to_html(text: str) -> str:
    raw = (text or "").replace("\r\n", "\n")
    if not raw.strip():
        return ""
    lines = raw.split("\n")
    chunks: list[str] = []
    i = 0
    in_list: str | None = None

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            chunks.append(f"</{in_list}>")
            in_list = None

    while i < len(lines):
        line = lines[i]
        if _FENCE.match(line.strip()):
            close_list()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not _FENCE.match(lines[i].strip()):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            chunks.append(
                "<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>"
            )
            continue
        if _is_table_start(lines, i):
            close_list()
            table_html, consumed = _table_html(lines, i)
            chunks.append(table_html)
            i += consumed
            continue
        stripped = line.strip()
        if not stripped:
            close_list()
            i += 1
            continue
        heading = _HEADING.match(stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            chunks.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue
        ul = _UL.match(stripped)
        if ul:
            if in_list != "ul":
                close_list()
                chunks.append("<ul>")
                in_list = "ul"
            chunks.append(f"<li>{_inline(ul.group(1))}</li>")
            i += 1
            continue
        ol = _OL.match(stripped)
        if ol:
            if in_list != "ol":
                close_list()
                chunks.append("<ol>")
                in_list = "ol"
            chunks.append(f"<li>{_inline(ol.group(2))}</li>")
            i += 1
            continue
        close_list()
        chunks.append(f"<p>{_inline(stripped)}</p>")
        i += 1
    close_list()
    return "\n".join(chunks)


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    return escaped


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return bool(_TABLE_ROW.match(lines[index])) and bool(_TABLE_SEP.match(lines[index + 1]))


def _split_row(line: str) -> list[str]:
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    return cells


def _table_html(lines: list[str], start: int) -> tuple[str, int]:
    header = _split_row(lines[start])
    rows: list[list[str]] = []
    i = start + 2
    while i < len(lines) and _TABLE_ROW.match(lines[i]) and not _TABLE_SEP.match(lines[i]):
        rows.append(_split_row(lines[i]))
        i += 1
    thead = "<tr>" + "".join(f"<th>{_inline(c)}</th>" for c in header) + "</tr>"
    body = []
    for row in rows:
        padded = row + [""] * max(0, len(header) - len(row))
        body.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in padded[: len(header)]) + "</tr>")
    html_table = f"<table><thead>{thead}</thead><tbody>{''.join(body)}</tbody></table>"
    return html_table, i - start


class MarkdownBody(QTextBrowser):
    def __init__(
        self,
        text: str = "",
        parent=None,
        *,
        font_size: int = 14,
        weight: QFont.Weight = QFont.Weight.Medium,
    ) -> None:
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.setMinimumWidth(0)
        self.document().setDocumentMargin(0)
        self.setFont(app_font(font_size, weight))
        family = self.font().family()
        color = MAIN_TEXT.name()
        self.setStyleSheet(
            f"""
            QTextBrowser {{
                background: transparent;
                border: none;
                color: {color};
                padding: 0;
            }}
            """
        )
        self.document().setDefaultStyleSheet(
            f"""
            body {{ color: {color}; font-family: '{family}'; font-size: {font_size}px; }}
            h1, h2, h3 {{ color: {color}; font-weight: 600; margin: 10px 0 6px 0; }}
            p {{ margin: 0 0 8px 0; }}
            ul, ol {{ margin: 4px 0 8px 18px; }}
            code {{ background: #F4F7F6; padding: 1px 4px; }}
            pre {{ background: #F4F7F6; padding: 8px; }}
            table {{ border-collapse: collapse; margin: 8px 0 12px 0; }}
            th, td {{ border: 1px solid #D5DEDA; padding: 6px 10px; }}
            th {{ background: #F4F7F6; font-weight: 600; }}
            """
        )
        self.set_markdown(text)
        self.document().contentsChanged.connect(self._fit_height)

    def set_markdown(self, text: str) -> None:
        body = markdown_to_html(text)
        self.setHtml(f"<html><body>{body}</body></html>" if body else "")
        self._fit_height()

    def _fit_height(self) -> None:
        width = self.viewport().width() or self.width()
        if width < 80:
            parent = self.parentWidget()
            width = parent.width() if parent is not None and parent.width() >= 80 else 420
        self.document().setTextWidth(width)
        height = int(self.document().size().height()) + 6
        self.setFixedHeight(max(24, height))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_height()

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())
