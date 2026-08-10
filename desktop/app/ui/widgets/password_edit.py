from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QProxyStyle,
    QStyle,
    QToolButton,
    QWidget,
)

from app.ui.theme import app_font


class _StarPasswordStyle(QProxyStyle):
    """Force classic asterisk mask instead of the platform password glyph."""

    def styleHint(self, hint, option=None, widget=None, returnData=None):  # noqa: N802
        if hint == QStyle.StyleHint.SH_LineEdit_PasswordCharacter:
            return ord("*")
        if hint == QStyle.StyleHint.SH_LineEdit_PasswordMaskDelay:
            return 0
        return super().styleHint(hint, option, widget, returnData)


class _EyeButton(QToolButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._open = True
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(34, 34)
        self.setAutoRaise(True)

    def set_open(self, open_eye: bool) -> None:
        self._open = open_eye
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(245, 247, 246, 200 if self.underMouse() else 170)
        pen = QPen(color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)

        cx, cy = self.width() / 2, self.height() / 2
        p.drawEllipse(QRectF(cx - 9, cy - 5.5, 18, 11))
        p.setBrush(color)
        p.drawEllipse(QRectF(cx - 2.8, cy - 2.8, 5.6, 5.6))
        if not self._open:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawLine(int(cx - 10), int(cy + 7), int(cx + 10), int(cy - 7))
        p.end()


class PasswordEdit(QWidget):
    """Password field with asterisk mask and show/hide eye toggle."""

    returnPressed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._visible = False

        self._edit = QLineEdit(self)
        self._edit.setStyle(_StarPasswordStyle(self._edit.style()))
        self._edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._edit.setPlaceholderText("Пароль 1С")
        self._edit.setFont(app_font(13, QFont.Weight.Medium))
        self._edit.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._edit.returnPressed.connect(self.returnPressed.emit)

        self._eye = _EyeButton(self)
        self._eye.clicked.connect(self._toggle_visibility)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 6, 0)
        lay.setSpacing(0)
        lay.addWidget(self._edit, 1)
        lay.addWidget(self._eye, 0, Qt.AlignmentFlag.AlignVCenter)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            """
            PasswordEdit {
                background: rgba(0, 0, 0, 0.35);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 22px;
            }
            PasswordEdit:hover {
                border: 1px solid rgba(255,255,255,0.35);
            }
            PasswordEdit QLineEdit {
                background: transparent;
                color: #f5f7f6;
                border: none;
                padding: 10px 8px 10px 18px;
                min-height: 24px;
                selection-background-color: #0a4a38;
            }
            PasswordEdit QToolButton {
                background: transparent;
                border: none;
                border-radius: 17px;
            }
            PasswordEdit QToolButton:hover {
                background: rgba(255,255,255,0.08);
            }
            """
        )
        self._sync_eye()

    def text(self) -> str:
        return self._edit.text()

    def clear(self) -> None:
        self._edit.clear()
        if self._visible:
            self._visible = False
            self._edit.setEchoMode(QLineEdit.EchoMode.Password)
            self._sync_eye()

    def setFocus(self, reason: Qt.FocusReason = Qt.FocusReason.OtherFocusReason) -> None:  # noqa: N802
        self._edit.setFocus(reason)

    def _toggle_visibility(self) -> None:
        self._visible = not self._visible
        self._edit.setEchoMode(
            QLineEdit.EchoMode.Normal if self._visible else QLineEdit.EchoMode.Password
        )
        self._sync_eye()
        self._edit.setFocus(Qt.FocusReason.OtherFocusReason)

    def _sync_eye(self) -> None:
        self._eye.set_open(not self._visible)
        self._eye.setToolTip("Скрыть пароль" if self._visible else "Показать пароль")
