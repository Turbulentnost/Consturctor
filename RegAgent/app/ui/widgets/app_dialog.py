from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.ui.styles import dialog_qss, primary_button_qss, secondary_button_qss
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font


class AppDialog(QDialog):
    def __init__(
        self,
        title: str,
        *,
        message: str = "",
        parent: QWidget | None = None,
        primary: str = "OK",
        secondary: str = "",
        danger: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("AppDialog")
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setStyleSheet(dialog_qss())

        card = QFrame()
        card.setObjectName("AppDialogCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(22, 20, 22, 18)
        inner.setSpacing(12)

        heading = QLabel(title)
        heading.setWordWrap(True)
        heading.setFont(app_font(18, QFont.Weight.DemiBold))
        heading.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        inner.addWidget(heading)

        self._body_host = QVBoxLayout()
        self._body_host.setContentsMargins(0, 0, 0, 0)
        self._body_host.setSpacing(8)
        if message:
            caption = QLabel(message)
            caption.setWordWrap(True)
            caption.setFont(app_font(13))
            caption.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
            self._body_host.addWidget(caption)
        inner.addLayout(self._body_host, 1)

        self._primary = QPushButton(primary)
        self._primary.setCursor(Qt.CursorShape.PointingHandCursor)
        self._primary.setFixedHeight(38)
        self._primary.setFont(app_font(13, QFont.Weight.DemiBold))
        self._primary.setStyleSheet(primary_button_qss(radius=12))
        self._primary.clicked.connect(self.accept)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        actions.addStretch(1)
        if secondary:
            cancel = QPushButton(secondary)
            cancel.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel.setFixedHeight(38)
            cancel.setFont(app_font(13, QFont.Weight.DemiBold))
            cancel.setStyleSheet(secondary_button_qss(radius=12))
            cancel.clicked.connect(self.reject)
            actions.addWidget(cancel)
        if danger:
            from app.ui.styles import danger_button_qss

            self._primary.setStyleSheet(danger_button_qss(radius=12))
        actions.addWidget(self._primary)
        inner.addLayout(actions)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.addWidget(card)

    def add_body(self, widget: QWidget) -> None:
        self._body_host.addWidget(widget)


def confirm_dialog(
    parent: QWidget | None,
    title: str,
    message: str,
    *,
    primary: str = "Да",
    secondary: str = "Отмена",
    danger: bool = False,
) -> bool:
    dialog = AppDialog(
        title,
        message=message,
        parent=parent,
        primary=primary,
        secondary=secondary,
        danger=danger,
    )
    return dialog.exec() == QDialog.DialogCode.Accepted


def info_dialog(parent: QWidget | None, title: str, message: str) -> None:
    AppDialog(title, message=message, parent=parent, primary="Понятно").exec()
