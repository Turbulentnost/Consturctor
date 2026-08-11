from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import MINT, SIDEBAR_MIDDLE, app_font

_TEMP = Path(__file__).resolve().parents[1] / "temp"
_UPLOAD_ICON = _TEMP / "Редактировать.png"
_CREATE_ICON = _TEMP / "Создать.png"

_ALLOWED_EXTENSIONS = {".docx", ".doc", ".pdf", ".md", ".txt"}
_FILTER = "Документы (*.docx *.doc *.pdf *.md *.txt)"


def _load_icon(path: Path, size: int = 72) -> QPixmap:
    """Load PNG and punch out near-black background for use on light cards."""
    if not path.exists():
        return QPixmap()
    src = QImage(str(path))
    if src.isNull():
        return QPixmap()
    img = src.convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = QColor.fromRgba(img.pixel(x, y))
            if c.red() < 48 and c.green() < 48 and c.blue() < 48:
                c.setAlpha(0)
                img.setPixelColor(x, y, c)
    pm = QPixmap.fromImage(img)
    return pm.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class RegulationDropZone(QWidget):
    """Compact dashed drop area for a regulation file."""

    file_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._hover = False
        self._file_path: str | None = None

        self._title = QLabel("Перетащите файл сюда")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setFont(app_font(14, QFont.Weight.DemiBold))
        self._title.setStyleSheet("color: #101817; background: transparent;")

        self._hint = QLabel('или <a href="pick" style="color:#2B6CB0;">выберите на компьютере</a>')
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._hint.setFont(app_font(12))
        self._hint.setStyleSheet("color: #6B7773; background: transparent;")
        self._hint.setTextFormat(Qt.TextFormat.RichText)
        self._hint.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self._hint.setOpenExternalLinks(False)
        self._hint.linkActivated.connect(lambda _href: self._pick_file())

        formats = QLabel("DOC, DOCX, PDF, MD, TXT")
        formats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        formats.setFont(app_font(11))
        formats.setStyleSheet("color: #9AA6A1; background: transparent;")

        self._file_label = QLabel("")
        self._file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._file_label.setFont(app_font(12, QFont.Weight.Medium))
        self._file_label.setStyleSheet("color: #06483D; background: transparent;")
        self._file_label.setWordWrap(True)
        self._file_label.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(5)
        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addWidget(self._hint)
        layout.addWidget(formats)
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

        bg = QColor("#EAF7F3" if self._hover else "#F4F7F6")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 14, 14)

        border = QColor(MINT if self._hover else SIDEBAR_MIDDLE)
        if not self._hover:
            border.setAlpha(70)
        pen = QPen(border, 1.8, Qt.PenStyle.DashLine)
        pen.setDashPattern([4, 3])
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 11, 11)
        painter.end()

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Выберите регламент", "", _FILTER)
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
        self._title.setText("Файл выбран")
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


class OptionCard(QFrame):
    """White rounded card for one creation path."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OptionCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setMinimumWidth(300)
        self.setMaximumHeight(360)
        self.setStyleSheet(
            """
            QFrame#OptionCard {
                background: #FFFFFF;
                border: 1px solid rgba(16, 24, 23, 0.10);
                border-radius: 22px;
            }
            """
        )


class CreateAgentPage(QWidget):
    create_regulation_requested = Signal()
    regulation_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("Создать ИИ-агента")
        title.setFont(app_font(32, QFont.Weight.DemiBold))
        title.setStyleSheet("color: #101817; background: transparent;")

        subtitle = QLabel("Начните с готового регламента или создайте его вместе с ИИ")
        subtitle.setFont(app_font(15))
        subtitle.setStyleSheet("color: #6B7773; background: transparent;")
        subtitle.setWordWrap(True)

        self._upload_card = self._build_upload_card()
        self._create_card = self._build_create_card()

        cards = QHBoxLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(22)
        cards.addWidget(self._upload_card, 1)
        cards.addWidget(self._create_card, 1)

        footer = QLabel("Регламент можно будет проверить и отредактировать перед созданием агента")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setFont(app_font(12))
        footer.setStyleSheet("color: #9AA6A1; background: transparent;")
        footer.setWordWrap(True)

        # Leave room on the right for the floating user menu in the shell header.
        title.setContentsMargins(0, 0, 280, 0)
        subtitle.setContentsMargins(0, 0, 280, 0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(36)
        layout.addLayout(cards, 0)
        layout.addStretch(1)
        layout.addWidget(footer)

    def selected_regulation_path(self) -> str | None:
        return self._drop_zone.selected_path()

    def _build_upload_card(self) -> OptionCard:
        card = OptionCard(self)
        icon = QLabel()
        icon.setFixedSize(72, 72)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "background: #EEF7F3; border-radius: 36px; border: 1px solid rgba(6,72,61,0.08);"
        )
        pm = _load_icon(_UPLOAD_ICON, 48)
        if not pm.isNull():
            icon.setPixmap(pm)

        heading = QLabel("Загрузить регламент")
        heading.setFont(app_font(18, QFont.Weight.DemiBold))
        heading.setStyleSheet("color: #101817; background: transparent;")
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        desc = QLabel("Прикрепите готовый документ — мы проанализируем его и спланируем работу агента")
        desc.setFont(app_font(13))
        desc.setStyleSheet("color: #6B7773; background: transparent;")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._drop_zone = RegulationDropZone(card)
        self._drop_zone.file_selected.connect(self.regulation_selected.emit)

        # Match the right card's badge row so icon/title align across both cards.
        badge_spacer = QWidget()
        badge_spacer.setFixedHeight(28)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(26, 20, 26, 24)
        lay.setSpacing(10)
        lay.addWidget(badge_spacer)
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(heading)
        lay.addWidget(desc)
        lay.addSpacing(8)
        lay.addWidget(self._drop_zone, 0)
        return card

    def _build_create_card(self) -> OptionCard:
        card = OptionCard(self)

        badge = QLabel("Нет регламента?")
        badge.setFont(app_font(11, QFont.Weight.DemiBold))
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedHeight(28)
        badge.setStyleSheet(
            """
            QLabel {
                background: #DFF5EC;
                color: #0A5C48;
                border-radius: 14px;
                padding: 0 12px;
            }
            """
        )

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addStretch(1)
        top.addWidget(badge)

        icon = QLabel()
        icon.setFixedSize(72, 72)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(
            "background: #EEF7F3; border-radius: 36px; border: 1px solid rgba(6,72,61,0.08);"
        )
        pm = _load_icon(_CREATE_ICON, 48)
        if not pm.isNull():
            icon.setPixmap(pm)

        heading = QLabel("Создать с помощью ИИ")
        heading.setFont(app_font(18, QFont.Weight.DemiBold))
        heading.setStyleSheet("color: #101817; background: transparent;")
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        desc = QLabel(
            "Ответьте на несколько вопросов — ИИ поможет оформить регламент и подготовить агента"
        )
        desc.setFont(app_font(13))
        desc.setStyleSheet("color: #6B7773; background: transparent;")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        button = QPushButton("Создать регламент")
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setFixedHeight(46)
        button.setFont(app_font(14, QFont.Weight.DemiBold))
        button.setStyleSheet(
            """
            QPushButton {
                background: #06483D;
                color: #F7FBFA;
                border: none;
                border-radius: 23px;
                padding: 0 22px;
            }
            QPushButton:hover { background: #08745F; }
            QPushButton:pressed { background: #04342C; }
            """
        )
        button.clicked.connect(self.create_regulation_requested.emit)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(26, 20, 26, 24)
        lay.setSpacing(10)
        lay.addLayout(top)
        lay.addWidget(icon, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(heading)
        lay.addWidget(desc)
        lay.addSpacing(8)
        lay.addWidget(button)
        return card
