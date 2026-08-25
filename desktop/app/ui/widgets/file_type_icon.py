"""Color file-type icons for the agent files list."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

_CACHE: dict[tuple[str, int], QPixmap] = {}


@dataclass(frozen=True, slots=True)
class FileTypeStyle:
    ext: str
    color: str
    soft: str
    glyph: str
    kind: str


_STYLES: dict[str, FileTypeStyle] = {
    "doc": FileTypeStyle("DOC", "#2B7DE9", "#E8F1FC", "W", "word"),
    "docx": FileTypeStyle("DOCX", "#2B7DE9", "#E8F1FC", "W", "word"),
    "odt": FileTypeStyle("ODT", "#2B7DE9", "#E8F1FC", "W", "word"),
    "rtf": FileTypeStyle("RTF", "#2B7DE9", "#E8F1FC", "W", "word"),
    "xls": FileTypeStyle("XLS", "#21A366", "#E6F6EE", "X", "excel"),
    "xlsx": FileTypeStyle("XLSX", "#21A366", "#E6F6EE", "X", "excel"),
    "ods": FileTypeStyle("ODS", "#21A366", "#E6F6EE", "X", "excel"),
    "csv": FileTypeStyle("CSV", "#21A366", "#E6F6EE", "X", "excel"),
    "ppt": FileTypeStyle("PPT", "#D24726", "#FBE9E6", "P", "slides"),
    "pptx": FileTypeStyle("PPTX", "#D24726", "#FBE9E6", "P", "slides"),
    "odp": FileTypeStyle("ODP", "#D24726", "#FBE9E6", "P", "slides"),
    "pdf": FileTypeStyle("PDF", "#E24B4A", "#FDECEC", "P", "pdf"),
    "txt": FileTypeStyle("TXT", "#5B6B7A", "#EEF1F3", "T", "text"),
    "log": FileTypeStyle("LOG", "#5B6B7A", "#EEF1F3", "L", "text"),
    "md": FileTypeStyle("MD", "#08745F", "#E7F5F1", "M", "text"),
    "markdown": FileTypeStyle("MD", "#08745F", "#E7F5F1", "M", "text"),
    "json": FileTypeStyle("JSON", "#C47E00", "#FBF3E2", "{}", "code"),
    "xml": FileTypeStyle("XML", "#E86B1F", "#FDEDE4", "</>", "code"),
    "html": FileTypeStyle("HTML", "#E86B1F", "#FDEDE4", "</>", "code"),
    "htm": FileTypeStyle("HTM", "#E86B1F", "#FDEDE4", "</>", "code"),
    "yaml": FileTypeStyle("YAML", "#7B6BB0", "#F1EEF8", "Y", "code"),
    "yml": FileTypeStyle("YML", "#7B6BB0", "#F1EEF8", "Y", "code"),
    "png": FileTypeStyle("PNG", "#7C4DFF", "#F0EAFF", "I", "image"),
    "jpg": FileTypeStyle("JPG", "#7C4DFF", "#F0EAFF", "I", "image"),
    "jpeg": FileTypeStyle("JPEG", "#7C4DFF", "#F0EAFF", "I", "image"),
    "gif": FileTypeStyle("GIF", "#7C4DFF", "#F0EAFF", "I", "image"),
    "webp": FileTypeStyle("WEBP", "#7C4DFF", "#F0EAFF", "I", "image"),
    "bmp": FileTypeStyle("BMP", "#7C4DFF", "#F0EAFF", "I", "image"),
    "svg": FileTypeStyle("SVG", "#7C4DFF", "#F0EAFF", "I", "image"),
    "zip": FileTypeStyle("ZIP", "#6E7D79", "#EEF1F0", "Z", "archive"),
    "rar": FileTypeStyle("RAR", "#6E7D79", "#EEF1F0", "Z", "archive"),
    "7z": FileTypeStyle("7Z", "#6E7D79", "#EEF1F0", "Z", "archive"),
    "tar": FileTypeStyle("TAR", "#6E7D79", "#EEF1F0", "Z", "archive"),
    "gz": FileTypeStyle("GZ", "#6E7D79", "#EEF1F0", "Z", "archive"),
    "py": FileTypeStyle("PY", "#3776AB", "#E8F1F8", "Py", "code"),
    "js": FileTypeStyle("JS", "#C4A000", "#FBF6DC", "JS", "code"),
    "ts": FileTypeStyle("TS", "#3178C6", "#E7F0FA", "TS", "code"),
    "css": FileTypeStyle("CSS", "#2965F1", "#E8EFFF", "C", "code"),
}


def file_ext_label(name: str) -> str:
    suffix = Path(name or "").suffix.strip(".").upper()
    return suffix or "FILE"


def file_type_style(name: str) -> FileTypeStyle:
    key = Path(name or "").suffix.strip(".").casefold()
    known = _STYLES.get(key)
    if known is not None:
        return known
    label = file_ext_label(name)
    glyph = label[:2] if len(label) > 1 else (label or "F")
    return FileTypeStyle(label, "#6B7C78", "#EEF1F0", glyph, "file")


def file_type_pixmap(name: str, size: int = 32) -> QPixmap:
    style = file_type_style(name)
    cache_key = (style.ext, int(size))
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _paint_icon(painter, QRectF(0, 0, size, size), style)
    painter.end()
    _CACHE[cache_key] = pixmap
    return pixmap


def _paint_icon(painter: QPainter, rect: QRectF, style: FileTypeStyle) -> None:
    radius = min(rect.width(), rect.height()) * 0.22
    path = QPainterPath()
    path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
    painter.fillPath(path, QColor(style.color))
    inner = rect.adjusted(rect.width() * 0.18, rect.height() * 0.16, -rect.width() * 0.18, -rect.height() * 0.16)
    painter.setPen(QPen(QColor("#FFFFFF"), max(1.2, rect.width() * 0.06)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if style.kind == "pdf":
        _paint_document(painter, inner)
        return
    if style.kind == "image":
        _paint_image(painter, inner)
        return
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(9, int(rect.height() * (0.34 if len(style.glyph) > 1 else 0.46))))
    painter.setFont(font)
    painter.setPen(QColor("#FFFFFF"))
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, style.glyph)


def _paint_document(painter: QPainter, rect: QRectF) -> None:
    fold = min(rect.width(), rect.height()) * 0.28
    path = QPainterPath()
    path.moveTo(rect.left(), rect.top() + fold)
    path.lineTo(rect.left() + fold, rect.top())
    path.lineTo(rect.right(), rect.top())
    path.lineTo(rect.right(), rect.bottom())
    path.lineTo(rect.left(), rect.bottom())
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(rect.left(), rect.top() + fold, rect.left() + fold, rect.top() + fold)
    painter.drawLine(rect.left() + fold, rect.top() + fold, rect.left() + fold, rect.top())


def _paint_image(painter: QPainter, rect: QRectF) -> None:
    painter.drawRoundedRect(rect, 2, 2)
    mid_y = rect.center().y() + rect.height() * 0.08
    painter.drawLine(rect.left() + 1, mid_y, rect.center().x() - 1, rect.top() + rect.height() * 0.28)
    painter.drawLine(rect.center().x() - 1, rect.top() + rect.height() * 0.28, rect.right() - 1, rect.bottom() - 2)
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawEllipse(
        int(rect.left() + rect.width() * 0.18),
        int(rect.top() + rect.height() * 0.16),
        3,
        3,
    )


class FileTypeIcon(QLabel):
    def __init__(self, name: str, parent: QWidget | None = None, *, size: int = 32) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setPixmap(file_type_pixmap(name, size))
        self.setStyleSheet("background: transparent; border: none;")


def elide_filename_middle(name: str, *, max_chars: int = 22) -> str:
    raw = (name or "").strip() or "file"
    if max_chars <= 4 or len(raw) <= max_chars:
        return raw
    suffix = Path(raw).suffix
    stem = raw[: -len(suffix)] if suffix and raw.endswith(suffix) else raw
    keep = max(1, max_chars - len(suffix) - 3)
    if len(stem) <= keep:
        return raw
    return f"{stem[:keep]}...{suffix}"


class ElidedFilenameLabel(QLabel):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = name or "file"
        self.setWordWrap(False)
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setToolTip(self._full)
        self.setStyleSheet("background: transparent; border: none;")
        self._apply_elide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        width = max(40, self.width())
        text = QFontMetrics(self.font()).elidedText(
            self._full,
            Qt.TextElideMode.ElideMiddle,
            width,
        )
        self.setText(text)
