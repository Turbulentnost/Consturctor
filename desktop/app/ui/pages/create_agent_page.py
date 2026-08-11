from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import MINT, SIDEBAR_MIDDLE, app_font

_ALLOWED_EXTENSIONS = {".docx", ".doc", ".pdf", ".md", ".txt"}
_FILTER = "Документы (*.docx *.doc *.pdf *.md *.txt)"


class RegulationDropZone(QWidget):
    """Центральная область drag-and-drop для регламента."""

    file_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(240)
        self.setMinimumWidth(420)
        self.setMaximumWidth(640)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._hover = False
        self._file_path: str | None = None

        title = QLabel("Перетащите файл сюда")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(app_font(18, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        hint = QLabel("или нажмите, чтобы выбрать · DOC, DOCX, PDF, MD, TXT")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(app_font(13))
        hint.setStyleSheet("color: #6B7773; background: transparent;")
        hint.setWordWrap(True)

        self._file_label = QLabel("")
        self._file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_label.setFont(app_font(13, QFont.Weight.Medium))
        self._file_label.setStyleSheet("color: #06483D; background: transparent;")
        self._file_label.setWordWrap(True)
        self._file_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 36, 32, 36)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        layout.addWidget(self._file_label)
        layout.addStretch(1)

    def selected_path(self) -> str | None:
        return self._file_path

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._pick_file()
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if self._has_allowed_urls(event):
            event.acceptProposedAction()
            self._hover = True
            self.update()
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = self._paths_from_mime(event.mimeData())
        self._hover = False
        self.update()
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self._apply_file(paths[0])

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(1, 1, -1, -1)

        bg = QColor("#EAF7F3" if self._hover else "#F3FAF7")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 18, 18)

        border = QColor(MINT if self._hover else SIDEBAR_MIDDLE)
        if not self._hover:
            border.setAlpha(90)
        pen = QPen(border, 2, Qt.PenStyle.DashLine)
        pen.setDashPattern([5, 4])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(4, 4, -4, -4), 14, 14)
        painter.end()

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите регламент",
            "",
            _FILTER,
        )
        if path:
            self._apply_file(path)

    def _apply_file(self, path: str) -> None:
        suffix = Path(path).suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            QMessageBox.warning(
                self,
                "Неверный формат",
                "Допустимы только файлы: DOC, DOCX, PDF, MD, TXT.",
            )
            return
        self._file_path = path
        self._file_label.setText(Path(path).name)
        self._file_label.show()
        self.file_selected.emit(path)
        self.update()

    @staticmethod
    def _paths_from_mime(mime) -> list[str]:
        if mime is None or not mime.hasUrls():
            return []
        out: list[str] = []
        for url in mime.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if Path(path).suffix.lower() in _ALLOWED_EXTENSIONS:
                out.append(path)
        return out

    def _has_allowed_urls(self, event: QDragEnterEvent) -> bool:
        return bool(self._paths_from_mime(event.mimeData()))


class CreateAgentPage(QWidget):
    create_regulation_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("Создать агента")
        title.setFont(app_font(34, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        self._drop_zone = RegulationDropZone()

        caption = QLabel("Прикрепите регламент, чтобы создать ИИ-агента")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setFont(app_font(16))
        caption.setStyleSheet("color: #6B7773; background: transparent;")
        caption.setWordWrap(True)

        no_reg = QLabel(
            'Нет регламента, <a href="create-regulation" style="color:#06483D; text-decoration: underline;">создать</a>'
        )
        no_reg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_reg.setFont(app_font(14))
        no_reg.setStyleSheet("color: #6B7773; background: transparent;")
        no_reg.setTextFormat(Qt.TextFormat.RichText)
        no_reg.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        no_reg.setOpenExternalLinks(False)
        no_reg.linkActivated.connect(lambda _href: self.create_regulation_requested.emit())

        center = QVBoxLayout()
        center.setSpacing(18)
        center.setContentsMargins(0, 0, 0, 0)
        center.addWidget(self._drop_zone, 0, Qt.AlignmentFlag.AlignHCenter)
        center.addWidget(caption)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addLayout(center)
        layout.addStretch(2)
        layout.addWidget(no_reg)

    def selected_regulation_path(self) -> str | None:
        return self._drop_zone.selected_path()
