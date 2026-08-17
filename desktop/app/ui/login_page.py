from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, LoginResult
from app.config import backend_url
from app.session_store import clear_session, remember_preference, save_backend_url, save_session, saved_fio
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
        self._register_mode = False
        self._registration_enabled = True

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

        self._subtitle = QLabel("Вход через учётную запись 1С")
        self._subtitle.setFont(app_font(13))
        self._subtitle.setStyleSheet("color: rgba(255,255,255,0.72); background: transparent;")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._hint = QLabel("Укажите ФИО и пароль из erp_pm")
        self._hint.setFont(app_font(12))
        self._hint.setStyleSheet("color: rgba(255,255,255,0.45); background: transparent;")
        self._hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

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

        self.department_edit = QLineEdit()
        self.department_edit.setPlaceholderText("Отдел (необязательно)")
        self.department_edit.setStyleSheet(field_qss)
        self.department_edit.returnPressed.connect(self._submit)
        self.department_edit.setVisible(False)

        self.server_edit = QLineEdit(backend_url())
        self.server_edit.setPlaceholderText("http://192.168.1.157:7812")
        self.server_edit.setStyleSheet(field_qss)

        fio_label = QLabel("ФИО")
        fio_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        fio_label.setFont(app_font(11, QFont.Weight.DemiBold))
        pwd_label = QLabel("Пароль")
        pwd_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        pwd_label.setFont(app_font(11, QFont.Weight.DemiBold))
        self._dept_label = QLabel("Отдел")
        self._dept_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        self._dept_label.setFont(app_font(11, QFont.Weight.DemiBold))
        self._dept_label.setVisible(False)
        server_label = QLabel("Сервер backend")
        server_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        server_label.setFont(app_font(11, QFont.Weight.DemiBold))

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
        if saved:
            self.fio_edit.setText(saved)

        self.server_status = QLabel("")
        self.server_status.setWordWrap(True)
        self.server_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.server_status.setStyleSheet("color: rgba(255,255,255,0.55); background: transparent;")
        self.server_status.setFont(app_font(11))

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

        self.mode_btn = QPushButton("Нет аккаунта? Зарегистрироваться")
        self.mode_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mode_btn.setFont(app_font(12))
        self.mode_btn.setStyleSheet(
            "QPushButton { color: rgba(255,255,255,0.72); background: transparent; border: none; }"
            "QPushButton:hover { color: #ffffff; }"
        )
        self.mode_btn.clicked.connect(self._toggle_mode)

        self.test_btn = QPushButton("Проверить связь")
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.setFont(app_font(12))
        self.test_btn.setStyleSheet(
            """
            QPushButton {
                background: rgba(255,255,255,0.12);
                color: #f5f7f6;
                border: 1px solid rgba(255,255,255,0.22);
                border-radius: 18px;
                padding: 6px 16px;
            }
            QPushButton:hover { background: rgba(255,255,255,0.18); }
            """
        )
        self.test_btn.clicked.connect(self._test_server)

        card_layout = QVBoxLayout(self._card)
        card_layout.setContentsMargins(40, 36, 40, 36)
        card_layout.setSpacing(10)
        if logo_path.exists():
            card_layout.addWidget(logo)
        card_layout.addWidget(brand)
        card_layout.addWidget(self._subtitle)
        card_layout.addWidget(self._hint)
        card_layout.addSpacing(18)
        card_layout.addWidget(fio_label)
        card_layout.addWidget(self.fio_edit)
        card_layout.addSpacing(6)
        card_layout.addWidget(pwd_label)
        card_layout.addWidget(self.password_edit)
        card_layout.addSpacing(6)
        card_layout.addWidget(self._dept_label)
        card_layout.addWidget(self.department_edit)
        card_layout.addSpacing(6)
        card_layout.addWidget(server_label)
        server_row = QHBoxLayout()
        server_row.setSpacing(8)
        server_row.addWidget(self.server_edit, 1)
        server_row.addWidget(self.test_btn)
        card_layout.addLayout(server_row)
        card_layout.addWidget(self.server_status)
        card_layout.addSpacing(4)
        card_layout.addWidget(self.remember_check)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.error_label)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.login_btn)
        card_layout.addWidget(self.mode_btn, 0, Qt.AlignmentFlag.AlignCenter)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self._card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

        self._card.setFixedWidth(460)

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
        fio = saved_fio()
        if fio:
            self.fio_edit.setText(fio)

    def _apply_server_url(self) -> bool:
        url = self.server_edit.text().strip().rstrip("/")
        if not url:
            self.error_label.setText("Укажите адрес сервера backend")
            return False
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"http://{url}"
            self.server_edit.setText(url)
        self._api.set_base_url(url)
        save_backend_url(url)
        return True

    def _test_server(self) -> None:
        if not self._apply_server_url():
            return
        self.server_status.setText("Проверка…")
        self.test_btn.setEnabled(False)
        try:
            health = self._api.health()
        except ApiError as exc:
            self.server_status.setText(f"Нет связи: {exc.message}")
            self._registration_enabled = False
        else:
            erp = "1С доступна" if health.erp_reachable else "1С недоступна"
            reg = "регистрация открыта" if health.registration_enabled else "только вход 1С"
            dev = "режим разработчика" if health.dev_mode else "прод"
            self.server_status.setText(
                f"Сервер {health.status}. {erp}. LLM: {health.llm_provider}. {reg}. {dev}."
            )
            self._registration_enabled = health.registration_enabled
            if not health.registration_enabled and self._register_mode:
                self._toggle_mode(force_login=True)
        finally:
            self.test_btn.setEnabled(True)

    def _toggle_mode(self, *, force_login: bool = False) -> None:
        if force_login:
            self._register_mode = False
        else:
            self._register_mode = not self._register_mode
        self.department_edit.setVisible(self._register_mode)
        self._dept_label.setVisible(self._register_mode)
        if self._register_mode:
            self._subtitle.setText("Регистрация локального аккаунта")
            self._hint.setText("Если 1С недоступна — создайте аккаунт на сервере конструктора")
            self.login_btn.setText("Зарегистрироваться")
            self.mode_btn.setText("Уже есть аккаунт? Войти")
            if not self._registration_enabled:
                self.error_label.setText("Регистрация отключена на этом сервере")
        else:
            self._subtitle.setText("Вход через учётную запись 1С")
            self._hint.setText("Укажите ФИО и пароль из erp_pm")
            self.login_btn.setText("Войти")
            self.mode_btn.setText("Нет аккаунта? Зарегистрироваться")
            self.error_label.setText("")

    def _search_fios(self, query: str) -> list[str]:
        if not self._apply_server_url():
            return []
        try:
            return self._api.search_users(query)
        except ApiError:
            return []

    def _submit(self) -> None:
        fio = self.fio_edit.text().strip()
        password = self.password_edit.text()
        self.error_label.setText("")

        if not fio or not password:
            self.error_label.setText("Введите ФИО и пароль")
            return
        if not self._apply_server_url():
            return

        self.login_btn.setEnabled(False)
        self.fio_edit.hide_suggestions()
        try:
            if self._register_mode:
                if not self._registration_enabled:
                    self.error_label.setText("Регистрация недоступна. Проверьте связь с сервером.")
                    return
                result: LoginResult = self._api.register(
                    fio,
                    password,
                    self.department_edit.text().strip(),
                )
            else:
                result = self._api.login(fio, password)
        except ApiError as exc:
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
