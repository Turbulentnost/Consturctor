from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

_AVATAR_SIZE = 42
_HEADER_WIDTH = 300
_DEFAULT_LOGO = Path(__file__).resolve().parents[1] / "temp" / "logo.png"
_HEADER_POSITION_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("комарков", "помощник председателя совета директоров"),
)


def _header_position(fio: str, position: str) -> str:
    key = (fio or "").casefold().replace("ь", "").replace("ъ", "")
    for needle, title in _HEADER_POSITION_OVERRIDES:
        if needle in key:
            return title
    return position.strip() or "должность не указана"


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        super().setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full_text = text
        self._sync_elide()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._sync_elide()

    def _sync_elide(self) -> None:
        width = max(0, self.width() - 2)
        if width <= 0:
            super().setText(self._full_text)
            return
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, width))


class RoundAvatarButton(QToolButton):
    """Circular avatar; falls back to app logo when no user photo."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setStyleSheet(
            """
            QToolButton {
                border: none;
                background: transparent;
                padding: 0;
            }
            QToolButton::menu-indicator { image: none; width: 0; }
            """
        )
        self.set_default_logo()

    def set_default_logo(self) -> None:
        if _DEFAULT_LOGO.exists():
            self.set_pixmap(QPixmap(str(_DEFAULT_LOGO)))
        else:
            self._pixmap = QPixmap()
            self.update()

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._pixmap = pixmap
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addEllipse(rect)

        p.fillPath(path, QColor("#06483D"))
        if not self._pixmap.isNull():
            p.setClipPath(path)
            scaled = self._pixmap.scaled(
                int(rect.width()),
                int(rect.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = rect.left() + (rect.width() - scaled.width()) / 2
            y = rect.top() + (rect.height() - scaled.height()) / 2
            p.drawPixmap(int(x), int(y), scaled)
            p.setClipping(False)

        p.setPen(QColor(6, 72, 61, 60))
        p.drawEllipse(rect)
        p.end()


class UserMenuHeader(QWidget):
    """Avatar + FIO; avatar opens Настроить / Выйти menu."""

    logout_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.avatar = RoundAvatarButton(self)
        menu = QMenu(self.avatar)
        menu.setFont(app_font(13))
        menu.setStyleSheet(
            """
            QMenu {
                background: #FAFCFB;
                color: #101817;
                border: 1px solid rgba(16,24,23,0.12);
                border-radius: 12px;
                padding: 6px;
            }
            QMenu::item {
                padding: 8px 18px;
                border-radius: 8px;
            }
            QMenu::item:selected {
                background: #E7F3EE;
            }
            """
        )
        settings_action = menu.addAction("Настроить")
        logout_action = menu.addAction("Выйти")
        settings_action.triggered.connect(self.settings_requested.emit)
        logout_action.triggered.connect(self.logout_requested.emit)
        self.avatar.setMenu(menu)

        self._fio = ElidedLabel("—")
        self._fio.setFont(app_font(15, QFont.Weight.DemiBold))
        self._fio.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._fio.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._fio.setMinimumWidth(0)
        self._fio.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self._position = ElidedLabel("")
        self._position.setFont(app_font(12))
        self._position.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._position.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._position.setMinimumWidth(0)
        self._position.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        text_col.addWidget(self._fio)
        text_col.addWidget(self._position)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(text_col, 1)
        self.setFixedWidth(_HEADER_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)

    def set_user(self, *, fio: str, position: str = "") -> None:
        self._fio.setText(fio or "—")
        self._position.setText(_header_position(fio, position))

    def set_avatar_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self.avatar.set_default_logo()
        else:
            self.avatar.set_pixmap(pixmap)
