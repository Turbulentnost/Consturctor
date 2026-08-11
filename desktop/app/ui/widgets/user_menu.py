from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
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
_DEFAULT_LOGO = Path(__file__).resolve().parents[1] / "temp" / "logo.png"


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

        self._fio = QLabel("—")
        self._fio.setFont(app_font(15, QFont.Weight.DemiBold))
        self._fio.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._fio.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._position = QLabel("")
        self._position.setFont(app_font(12))
        self._position.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._position.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        text_col = QVBoxLayout()
        text_col.setContentsMargins(0, 0, 0, 0)
        text_col.setSpacing(1)
        text_col.addWidget(self._fio)
        text_col.addWidget(self._position)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)
        root.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(text_col, 0)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)

    def set_user(self, *, fio: str, position: str = "") -> None:
        self._fio.setText(fio or "—")
        self._position.setText(position.strip() or "должность не указана")

    def set_avatar_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self.avatar.set_default_logo()
        else:
            self.avatar.set_pixmap(pixmap)
