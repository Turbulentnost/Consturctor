from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, UserProfile
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

_AVATAR_SIZE = 128
_DEFAULT_LOGO = Path(__file__).resolve().parents[1] / "temp" / "logo.png"


class ProfileAvatar(QWidget):
    """Large round avatar with camera overlay on hover."""

    change_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._hover = False
        self.setFixedSize(_AVATAR_SIZE, _AVATAR_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_default_logo()

    def set_default_logo(self) -> None:
        if _DEFAULT_LOGO.exists():
            self.set_pixmap(QPixmap(str(_DEFAULT_LOGO)))
        else:
            self._pixmap = QPixmap()
            self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        if pixmap is None or pixmap.isNull():
            self.set_default_logo()
            return
        self._pixmap = pixmap
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.pos()):
            self.change_requested.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        rect = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
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

        p.setPen(QPen(QColor(6, 72, 61, 70), 2))
        p.drawEllipse(rect)

        if self._hover:
            p.setClipPath(path)
            p.fillRect(rect, QColor(0, 0, 0, 120))
            p.setClipping(False)
            self._draw_camera(p, rect.center().x(), rect.center().y())

        p.end()

    def _draw_camera(self, p: QPainter, cx: float, cy: float) -> None:
        color = QColor("#F7FBFA")
        pen = QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        body = QRectF(cx - 16, cy - 8, 32, 20)
        p.drawRoundedRect(body, 4, 4)
        p.drawEllipse(QRectF(cx - 7, cy - 4, 14, 14))
        p.drawEllipse(QRectF(cx - 3, cy, 6, 6))
        p.drawRoundedRect(QRectF(cx - 6, cy - 13, 12, 6), 2, 2)


class _PencilButton(QToolButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(28, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Изменить отдел")
        self.setStyleSheet(
            """
            QToolButton {
                background: transparent;
                border: none;
                border-radius: 14px;
            }
            QToolButton:hover { background: rgba(6,72,61,0.10); }
            QToolButton:disabled { background: transparent; }
            """
        )

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor("#6B7773") if self.isEnabled() else QColor("#B7C0BC")
        pen = QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # Pencil body
        p.drawLine(8, 18, 18, 8)
        p.drawLine(18, 8, 20, 10)
        p.drawLine(20, 10, 10, 20)
        p.drawLine(8, 18, 10, 20)
        # Tip
        p.drawLine(8, 18, 7, 21)
        p.drawLine(10, 20, 7, 21)
        p.end()


class SettingsPage(QWidget):
    profile_updated = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._user: UserProfile | None = None
        self._departments: list[str] = []
        self._editing_dept = False

        self.avatar = ProfileAvatar(self)
        self.avatar.change_requested.connect(self._pick_avatar)

        self._fio = QLabel("—")
        self._fio.setFont(app_font(26, QFont.Weight.DemiBold))
        self._fio.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._fio.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._dept = QLabel("")
        self._dept.setFont(app_font(15))
        self._dept.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._dept.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._dept.setWordWrap(True)
        self._dept.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self._pencil = _PencilButton(self)
        self._pencil.clicked.connect(self._start_edit_department)

        self._dept_combo = QComboBox(self)
        self._dept_combo.setFont(app_font(14))
        self._dept_combo.setMinimumWidth(360)
        self._dept_combo.setMaximumWidth(520)
        self._dept_combo.setVisible(False)
        self._dept_combo.setStyleSheet(
            """
            QComboBox {
                background: #FFFFFF;
                color: #101817;
                border: 1px solid rgba(16,24,23,0.16);
                border-radius: 12px;
                padding: 8px 14px;
                min-height: 22px;
            }
            QComboBox:hover { border: 1px solid rgba(6,72,61,0.45); }
            QComboBox::drop-down { border: none; width: 28px; }
            QComboBox QAbstractItemView {
                background: #FFFFFF;
                color: #101817;
                border: 1px solid rgba(16,24,23,0.12);
                selection-background-color: #E7F3EE;
                outline: none;
            }
            """
        )
        self._dept_combo.activated.connect(self._on_department_chosen)

        self._dept_hint = QLabel("")
        self._dept_hint.setFont(app_font(12))
        self._dept_hint.setStyleSheet("color: #9AA6A1; background: transparent;")
        self._dept_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._dept_hint.setWordWrap(True)

        dept_row = QHBoxLayout()
        dept_row.setContentsMargins(0, 0, 0, 0)
        dept_row.setSpacing(8)
        dept_row.addStretch(1)
        dept_row.addWidget(self._dept, 0, Qt.AlignmentFlag.AlignVCenter)
        dept_row.addWidget(self._pencil, 0, Qt.AlignmentFlag.AlignVCenter)
        dept_row.addStretch(1)

        combo_row = QHBoxLayout()
        combo_row.setContentsMargins(0, 0, 0, 0)
        combo_row.addStretch(1)
        combo_row.addWidget(self._dept_combo, 0)
        combo_row.addStretch(1)

        hint = QLabel("Наведите на фото и нажмите, чтобы сменить аватар")
        hint.setFont(app_font(12))
        hint.setStyleSheet("color: #9AA6A1; background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 24, 0, 0)
        layout.setSpacing(10)
        layout.addStretch(1)
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addSpacing(18)
        layout.addWidget(self._fio)
        layout.addLayout(dept_row)
        layout.addLayout(combo_row)
        layout.addWidget(self._dept_hint)
        layout.addSpacing(8)
        layout.addWidget(hint)
        layout.addStretch(2)

    def set_user(self, user: UserProfile, pixmap: QPixmap | None = None) -> None:
        self._user = user
        self._editing_dept = False
        self._fio.setText(user.fio or "—")
        self._dept.setText(user.department.strip() or "отдел не указан")
        self._dept.setVisible(True)
        self._pencil.setVisible(True)
        self._dept_combo.setVisible(False)
        self._sync_department_hint(user)
        if pixmap is not None and not pixmap.isNull():
            self.avatar.set_pixmap(pixmap)
        elif user.avatar_url:
            self._load_avatar(user.avatar_url)
        else:
            self.avatar.set_default_logo()

    def _sync_department_hint(self, user: UserProfile) -> None:
        if user.can_change_department:
            self._pencil.setEnabled(True)
            self._pencil.setToolTip("Изменить отдел")
            self._dept_hint.setText("Отдел можно менять не чаще одного раза в 2 недели")
            return
        self._pencil.setEnabled(True)  # still clickable to show cooldown message
        self._pencil.setToolTip("Смена отдела недоступна")
        if user.department_change_available_at is not None:
            local = user.department_change_available_at.astimezone().strftime("%d.%m.%Y")
            self._dept_hint.setText(f"Следующая смена отдела доступна с {local}")
        else:
            self._dept_hint.setText("Отдел можно менять не чаще одного раза в 2 недели")

    def _load_avatar(self, url: str) -> None:
        try:
            data = self._api.fetch_bytes(url)
        except ApiError:
            self.avatar.set_default_logo()
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            self.avatar.set_pixmap(pixmap)
        else:
            self.avatar.set_default_logo()

    def _pick_avatar(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите аватар",
            "",
            "Изображения (*.png *.jpg *.jpeg *.webp *.gif)",
        )
        if not path:
            return
        try:
            user = self._api.upload_avatar(path)
        except ApiError as exc:
            QMessageBox.warning(self, "Аватар", exc.message)
            return
        self.set_user(user)
        self.profile_updated.emit(user)

    def _start_edit_department(self) -> None:
        if self._user is None:
            return
        if not self._user.can_change_department:
            msg = self._dept_hint.text() or "Отдел можно менять раз в 2 недели"
            QMessageBox.information(self, "Отдел", msg)
            return

        if not self._departments:
            try:
                self._departments = self._api.list_departments()
            except ApiError as exc:
                QMessageBox.warning(self, "Отдел", exc.message)
                return
            if not self._departments:
                QMessageBox.warning(self, "Отдел", "Список отделов пуст")
                return

        self._editing_dept = True
        self._dept.setVisible(False)
        self._pencil.setVisible(False)
        self._dept_combo.blockSignals(True)
        self._dept_combo.clear()
        self._dept_combo.addItems(self._departments)
        current = (self._user.department or "").strip()
        idx = self._dept_combo.findText(current)
        if idx >= 0:
            self._dept_combo.setCurrentIndex(idx)
        self._dept_combo.blockSignals(False)
        self._dept_combo.setVisible(True)
        self._dept_combo.showPopup()

    def _on_department_chosen(self, index: int) -> None:
        if not self._editing_dept or index < 0:
            return
        department = self._dept_combo.itemText(index).strip()
        if not department:
            return
        if self._user and department == (self._user.department or "").strip():
            self.set_user(self._user)
            return
        try:
            user = self._api.update_department(department)
        except ApiError as exc:
            QMessageBox.warning(self, "Отдел", exc.message)
            if self._user is not None:
                self.set_user(self._user)
            return
        self.set_user(user)
        self.profile_updated.emit(user)
