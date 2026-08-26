from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, LoginResult
from app.session_store import clear_session, remember_preference, save_session, saved_fio
from app.ui.theme import app_font, circular_pixmap
from app.ui.widgets.fio_suggest import FioSuggestEdit
from app.ui.widgets.gradient_bg import GlassPanel, GradientBackground
from app.ui.widgets.password_edit import PasswordEdit

_CHECK_ICON = Path(__file__).resolve().parent / "temp" / "check_white.png"


def _ensure_check_icon() -> Path:
    if _CHECK_ICON.exists() and _CHECK_ICON.stat().st_size > 0:
        return _CHECK_ICON
    _CHECK_ICON.parent.mkdir(parents=True, exist_ok=True)
    pm = QPixmap(18, 18)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor("#FFFFFF"), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(4, 9, 8, 13)
    p.drawLine(8, 13, 14, 5)
    p.end()
    pm.save(str(_CHECK_ICON), "PNG")
    return _CHECK_ICON


class LoginPage(QWidget):
    logged_in = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api

        self._bg = GradientBackground(self)

        self._card = GlassPanel(self, radius=28)
        shadow = QGraphicsDropShadowEffect(self._card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 12)
        shadow.setColor(Qt.GlobalColor.black)
        self._card.setGraphicsEffect(shadow)

        logo_path = Path(__file__).resolve().parent / "temp" / "logo.png"
        logo = QLabel()
        logo.setFixedSize(54, 54)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("background: transparent; border-radius: 27px;")
        if logo_path.exists():
            logo.setPixmap(circular_pixmap(QPixmap(str(logo_path)), 54))

        brand = QLabel("turbobot")
        brand.setFont(app_font(28, QFont.Weight.Bold))
        brand.setStyleSheet("color: #f5f7f6; background: transparent;")
        brand.setAlignment(Qt.AlignmentFlag.AlignCenter)

        subtitle = QLabel("Вход через учётную запись 1С")
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet("color: rgba(255,255,255,0.72); background: transparent;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        hint = QLabel("Укажите ФИО и пароль из erp_pm")
        hint.setFont(app_font(12))
        hint.setStyleSheet("color: rgba(255,255,255,0.45); background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        field_qss = """
            QLineEdit {
                background: rgba(0, 0, 0, 0.35);
                color: #f5f7f6;
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 22px;
                padding: 10px 18px;
                min-height: 24px;
                selection-background-color: #0a4a38;
            }
            QLineEdit:hover, QLineEdit:focus {
                border: 1px solid rgba(255,255,255,0.35);
            }
        """

        self.fio_edit = FioSuggestEdit(self._search_fios)
        self.fio_edit.setStyleSheet(field_qss)
        self.fio_edit.returnPressed.connect(self._submit)

        self.password_edit = PasswordEdit()
        self.password_edit.returnPressed.connect(self._submit)

        fio_label = QLabel("ФИО")
        fio_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        fio_label.setFont(app_font(11, QFont.Weight.DemiBold))
        pwd_label = QLabel("Пароль")
        pwd_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        pwd_label.setFont(app_font(11, QFont.Weight.DemiBold))

        self.remember_check = QCheckBox("Запомнить пользователя")
        self.remember_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remember_check.setFont(app_font(12))
        self.remember_check.setChecked(remember_preference())
        check_icon = _ensure_check_icon().resolve().as_posix()
        self.remember_check.setStyleSheet(
            f"""
            QCheckBox {{
                color: rgba(255,255,255,0.72);
                background: transparent;
                spacing: 8px;
            }}
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 5px;
                border: 1px solid rgba(255,255,255,0.28);
                background: rgba(0, 0, 0, 0.28);
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid rgba(255,255,255,0.45);
            }}
            QCheckBox::indicator:checked {{
                background: #62E0BE;
                border: 1px solid #62E0BE;
                image: url("{check_icon}");
            }}
            """
        )

        saved = saved_fio()
        from app.chat.test_user import ZHALYBIN_FIO, is_ilchenko_user

        if not saved or is_ilchenko_user(fio=saved):
            saved = ZHALYBIN_FIO
        self.fio_edit.setText(saved)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.setStyleSheet("color: #ff8a80; background: transparent;")
        self.error_label.setFont(app_font(12))

        self.login_btn = QPushButton("Войти")
        self.login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.login_btn.setFont(app_font(14, QFont.Weight.DemiBold))
        self.login_btn.setFixedHeight(48)
        self.login_btn.setStyleSheet(
            """
            QPushButton {
                background: #ffffff;
                color: #0a1210;
                border: none;
                border-radius: 24px;
                padding: 0 28px;
            }
            QPushButton:hover { background: #eef5f1; }
            QPushButton:pressed { background: #dce8e2; }
            QPushButton:disabled { background: #9aaea5; color: #333; }
            """
        )
        self.login_btn.clicked.connect(self._submit)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(40, 36, 40, 36)
        card_layout.setSpacing(10)
        if logo_path.exists():
            card_layout.addWidget(logo)
        card_layout.addWidget(brand)
        card_layout.addWidget(subtitle)
        card_layout.addWidget(hint)
        card_layout.addSpacing(18)
        card_layout.addWidget(fio_label)
        card_layout.addWidget(self.fio_edit)
        card_layout.addSpacing(6)
        card_layout.addWidget(pwd_label)
        card_layout.addWidget(self.password_edit)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.remember_check)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.error_label)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.login_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self._card.setFixedWidth(440)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._bg.setGeometry(self.rect())
        self._bg.lower()

    def reset_form(self) -> None:
        self.fio_edit.hide_suggestions()
        self.password_edit.clear()
        self.error_label.setText("")
        self.login_btn.setEnabled(True)
        self.remember_check.setChecked(remember_preference())
        from app.chat.test_user import ZHALYBIN_FIO, is_ilchenko_user

        fio = saved_fio()
        if not fio or is_ilchenko_user(fio=fio):
            fio = ZHALYBIN_FIO
        self.fio_edit.setText(fio)

    def _search_fios(self, query: str) -> list[str]:
        return self._api.search_users(query)

    def _submit(self) -> None:
        fio = self.fio_edit.text().strip()
        password = self.password_edit.text()
        self.error_label.setText("")

        if not fio or not password:
            self.error_label.setText("Введите ФИО и пароль")
            return

        self.login_btn.setEnabled(False)
        self.fio_edit.hide_suggestions()
        from app.chat.test_user import is_test_credentials, test_login_result

        try:
            result = self._api.login(fio, password)
        except ApiError as exc:
            if is_test_credentials(fio, password):
                result = test_login_result(fio)
            else:
                self.error_label.setText(exc.message)
                if exc.status_code == 503:
                    QMessageBox.warning(self, "Сервис недоступен", exc.message)
                return
        finally:
            self.login_btn.setEnabled(True)

        if self.remember_check.isChecked():
            save_session(access_token=result.access_token, fio=result.user.fio)
        else:
            clear_session()

        self.fio_edit.hide_suggestions()
        self.logged_in.emit(result)
