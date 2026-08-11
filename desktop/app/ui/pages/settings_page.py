from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QFrame,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, UserProfile
from app.ui.theme import COLOR_CONTENT_MUTED, MAIN_TEXT, app_font

_AVATAR_SIZE = 128
_DEFAULT_LOGO = Path(__file__).resolve().parents[1] / "temp" / "logo.png"
_MAX_VISIBLE_ROWS = 6
_ROW_HEIGHT = 36
_POPUP_PAD = 8


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


class DepartmentSuggestEdit(QLineEdit):
    """Always-visible department input with a height-capped suggestion list."""

    department_chosen = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[str] = []
        self._can_edit = True
        self._committed = ""

        self.setFont(app_font(14))
        self.setMinimumWidth(360)
        self.setMaximumWidth(560)
        self.setFixedHeight(44)
        self.setPlaceholderText("Выберите или начните вводить отдел…")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            """
            QLineEdit {
                background: #FFFFFF;
                color: #101817;
                border: 1px solid rgba(16,24,23,0.16);
                border-radius: 12px;
                padding: 8px 14px;
            }
            QLineEdit:hover { border: 1px solid rgba(6,72,61,0.40); }
            QLineEdit:focus { border: 1px solid rgba(6,72,61,0.55); }
            QLineEdit:disabled {
                background: #F4F7F6;
                color: #6B7773;
                border: 1px solid rgba(16,24,23,0.10);
            }
            """
        )

        self._popup = QFrame(None)
        self._popup.hide()
        self._popup.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self._popup.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._popup.setStyleSheet(
            """
            QFrame {
                background: #FFFFFF;
                border: 1px solid rgba(16,24,23,0.12);
                border-radius: 12px;
            }
            """
        )

        self._list = QListWidget(self._popup)
        self._list.setFont(app_font(13))
        self._list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self._list.setUniformItemSizes(True)
        self._list.setStyleSheet(
            """
            QListWidget {
                background: transparent;
                color: #101817;
                border: none;
                outline: none;
                padding: 2px;
            }
            QListWidget::item {
                height: 34px;
                padding: 0 12px;
                border-radius: 8px;
            }
            QListWidget::item:hover,
            QListWidget::item:selected {
                background: #E7F3EE;
            }
            QScrollBar:vertical {
                background: transparent;
                width: 8px;
                margin: 4px 2px 4px 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(16,24,23,0.18);
                border-radius: 4px;
                min-height: 24px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            """
        )
        self._list.itemClicked.connect(self._on_item_clicked)

        lay = QVBoxLayout(self._popup)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(0)
        lay.addWidget(self._list)

        self.textEdited.connect(self._on_text_edited)
        self.returnPressed.connect(self._commit_from_text)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def set_items(self, items: list[str]) -> None:
        self._items = [x.strip() for x in items if x and x.strip()]
        self._refresh_list(self.text().strip())

    def set_department(self, value: str) -> None:
        text = value.strip()
        self._committed = text
        self.blockSignals(True)
        self.setText(text)
        self.blockSignals(False)
        self.hide_popup()

    def set_editable(self, enabled: bool) -> None:
        self._can_edit = enabled
        self.setReadOnly(not enabled)
        self.setEnabled(True)
        if not enabled:
            self.hide_popup()

    def hide_popup(self) -> None:
        self._popup.hide()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)
        if self._can_edit and event.button() == Qt.MouseButton.LeftButton:
            self._open_popup()

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        if self._can_edit:
            self._open_popup()

    def focusOutEvent(self, event) -> None:  # noqa: N802
        super().focusOutEvent(event)
        # Defer hide so list item click can fire first.
        QTimer.singleShot(0, self._maybe_close_popup)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (
            self._popup.isVisible()
            and event.type() == QEvent.Type.MouseButtonPress
            and isinstance(event, QMouseEvent)
        ):
            global_pos = event.globalPosition().toPoint()
            in_popup = self._popup.geometry().contains(global_pos)
            in_field = self.rect().contains(self.mapFromGlobal(global_pos))
            if not in_popup and not in_field:
                self.hide_popup()
                self._revert_if_incomplete()
        return super().eventFilter(obj, event)

    def _maybe_close_popup(self) -> None:
        focus = QApplication.focusWidget()
        if focus is self or self._popup.isAncestorOf(focus):
            return
        self.hide_popup()
        self._revert_if_incomplete()

    def _on_text_edited(self, text: str) -> None:
        if not self._can_edit:
            return
        self._refresh_list(text.strip())
        self._open_popup()

    def _open_popup(self) -> None:
        if not self._can_edit or not self._items:
            return
        self._refresh_list(self.text().strip())
        if self._list.count() == 0:
            self.hide_popup()
            return

        rows = min(self._list.count(), _MAX_VISIBLE_ROWS)
        height = rows * _ROW_HEIGHT + _POPUP_PAD
        width = max(self.width(), 360)
        self._popup.setFixedSize(width, height)

        pos = self.mapToGlobal(QPoint(0, self.height() + 4))
        screen = self.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            if pos.y() + height > geo.bottom() - 8:
                pos.setY(self.mapToGlobal(QPoint(0, 0)).y() - height - 4)
            if pos.x() + width > geo.right() - 8:
                pos.setX(geo.right() - width - 8)
            if pos.x() < geo.left() + 8:
                pos.setX(geo.left() + 8)
        self._popup.move(pos)
        self._popup.show()
        self._popup.raise_()

    def _refresh_list(self, query: str) -> None:
        q = query.casefold()
        self._list.clear()
        for name in self._items:
            if not q or q in name.casefold():
                self._list.addItem(QListWidgetItem(name))

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        value = item.text().strip()
        if not value:
            return
        self._apply_choice(value)

    def _commit_from_text(self) -> None:
        text = self.text().strip()
        if not text:
            return
        match = next((x for x in self._items if x.casefold() == text.casefold()), None)
        if match is None and self._list.count() == 1:
            match = self._list.item(0).text().strip()
        if match:
            self._apply_choice(match)

    def _apply_choice(self, value: str) -> None:
        self.blockSignals(True)
        self.setText(value)
        self.blockSignals(False)
        self.hide_popup()
        if value != self._committed:
            self._committed = value
            self.department_chosen.emit(value)

    def _revert_if_incomplete(self) -> None:
        current = self.text().strip()
        if current != self._committed and current not in self._items:
            self.blockSignals(True)
            self.setText(self._committed)
            self.blockSignals(False)


class SettingsPage(QWidget):
    profile_updated = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._user: UserProfile | None = None
        self._departments: list[str] = []

        self.avatar = ProfileAvatar(self)
        self.avatar.change_requested.connect(self._pick_avatar)

        self._fio = QLabel("—")
        self._fio.setFont(app_font(26, QFont.Weight.DemiBold))
        self._fio.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        self._fio.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self._dept_edit = DepartmentSuggestEdit(self)
        self._dept_edit.department_chosen.connect(self._on_department_chosen)

        self._dept_hint = QLabel("")
        self._dept_hint.setFont(app_font(12))
        self._dept_hint.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        self._dept_hint.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._dept_hint.setWordWrap(True)

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
        layout.addSpacing(4)
        layout.addWidget(self._dept_edit, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._dept_hint)
        layout.addSpacing(8)
        layout.addWidget(hint)
        layout.addStretch(2)

    def set_user(self, user: UserProfile, pixmap: QPixmap | None = None) -> None:
        self._user = user
        self._fio.setText(user.fio or "—")
        self._ensure_departments()
        self._dept_edit.set_items(self._departments)
        self._dept_edit.set_department(user.department.strip() or "")
        self._sync_department_hint(user)
        if pixmap is not None and not pixmap.isNull():
            self.avatar.set_pixmap(pixmap)
        elif user.avatar_url:
            self._load_avatar(user.avatar_url)
        else:
            self.avatar.set_default_logo()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._dept_edit.hide_popup()
        super().hideEvent(event)

    def _sync_department_hint(self, user: UserProfile) -> None:
        if user.can_change_department:
            self._dept_edit.set_editable(True)
            self._dept_hint.setText("Отдел можно менять не чаще одного раза в 2 недели")
            return
        self._dept_edit.set_editable(False)
        if user.department_change_available_at is not None:
            local = user.department_change_available_at.astimezone().strftime("%d.%m.%Y")
            self._dept_hint.setText(f"Следующая смена отдела доступна с {local}")
        else:
            self._dept_hint.setText("Отдел можно менять не чаще одного раза в 2 недели")

    def _ensure_departments(self) -> None:
        if self._departments:
            return
        try:
            self._departments = self._api.list_departments()
        except ApiError:
            self._departments = []

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

    def _on_department_chosen(self, department: str) -> None:
        department = department.strip()
        if not department or self._user is None:
            return
        if not self._user.can_change_department:
            QMessageBox.information(
                self,
                "Отдел",
                self._dept_hint.text() or "Отдел можно менять раз в 2 недели",
            )
            self._dept_edit.set_department(self._user.department.strip())
            return
        if department == (self._user.department or "").strip():
            return
        try:
            user = self._api.update_department(department)
        except ApiError as exc:
            QMessageBox.warning(self, "Отдел", exc.message)
            self._dept_edit.set_department(self._user.department.strip())
            return
        self.set_user(user)
        self.profile_updated.emit(user)
