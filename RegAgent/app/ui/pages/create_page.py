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
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.ui.styles import card_qss, dark_primary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, MINT, SIDEBAR_MIDDLE, app_font
from app.ui.widgets.app_dialog import info_dialog

_TEMP = Path(__file__).resolve().parents[1] / "temp"
_UPLOAD_ICON = _TEMP / "Редактировать.png"
_CREATE_ICON = _TEMP / "Создать.png"

_ALLOWED_EXTENSIONS = {".docx", ".doc", ".pdf", ".xlsx", ".md", ".txt"}
_FILTER = "Документы (*.docx *.doc *.pdf *.xlsx *.md *.txt)"


def _load_icon(path: Path, size: int = 72) -> QPixmap:
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

        formats = QLabel("DOC, DOCX, PDF, XLSX, MD, TXT")
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

    def clear(self) -> None:
        self._file_path = None
        self._file_label.hide()
        self._title.setText("Перетащите файл сюда")
        self.update()

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
            info_dialog(
                self,
                "Неверный формат",
                "Допустимы только файлы: DOC, DOCX, PDF, XLSX, MD, TXT.",
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
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("OptionCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.setMinimumWidth(300)
        self.setMaximumHeight(360)
        self.setStyleSheet(card_qss("OptionCard", radius=22, hover=True))
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        self._shadow.setColor(Qt.GlobalColor.black)
        self.setGraphicsEffect(self._shadow)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._shadow.setBlurRadius(28)
        self._shadow.setOffset(0, 8)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._shadow.setBlurRadius(0)
        self._shadow.setOffset(0, 0)
        super().leaveEvent(event)


class CreatePage(QWidget):
    analyze_requested = Signal()
    create_regulation_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        title = QLabel("Создать ИИ-агента")
        title.setFont(app_font(32, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        subtitle = QLabel("Начните с готового регламента или создайте его вместе с ИИ")
        subtitle.setFont(app_font(15))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
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

        self._loading = QFrame(self)
        self._loading.setObjectName("CreateLoading")
        self._loading.setStyleSheet(
            """
            QFrame#CreateLoading {
                background: rgba(250,252,251,0.88);
                border-radius: 18px;
            }
            """
        )
        load_title = QLabel("Распознаём документ…")
        load_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        load_title.setFont(app_font(20, QFont.Weight.DemiBold))
        load_title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        load_sub = QLabel("Это может занять около минуты")
        load_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        load_sub.setFont(app_font(13))
        load_sub.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedSize(280, 8)
        progress.setStyleSheet(
            """
            QProgressBar {
                background: rgba(6,72,61,0.12);
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: #08745F;
                border-radius: 4px;
            }
            """
        )
        load_lay = QVBoxLayout(self._loading)
        load_lay.setContentsMargins(32, 32, 32, 32)
        load_lay.addStretch(1)
        load_lay.addWidget(load_title)
        load_lay.addSpacing(8)
        load_lay.addWidget(load_sub)
        load_lay.addSpacing(20)
        load_lay.addWidget(progress, 0, Qt.AlignmentFlag.AlignHCenter)
        load_lay.addStretch(1)
        self._loading.hide()

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

    def selected_path(self) -> str | None:
        return self._drop_zone.selected_path()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._loading.setGeometry(self.rect())
        self._loading.raise_()

    def set_processing(self, active: bool) -> None:
        self._loading.setVisible(active)
        self._loading.raise_()
        self._upload_card.setEnabled(not active)
        self._create_card.setEnabled(not active)

    def reset(self) -> None:
        self._drop_zone.clear()
        self.set_processing(False)

    def _on_file_selected(self, _path: str) -> None:
        self.analyze_requested.emit()

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
        self._drop_zone.file_selected.connect(self._on_file_selected)

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
        button.setStyleSheet(dark_primary_button_qss())
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
