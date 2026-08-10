from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import (
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
from app.ui.theme import app_font
from app.ui.widgets.fio_suggest import FioSuggestEdit
from app.ui.widgets.gradient_bg import GlassPanel, GradientBackground


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
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        if logo_path.exists():
            pixmap = QPixmap(str(logo_path))
            logo.setPixmap(
                pixmap.scaled(
                    54,
                    54,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

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

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Пароль 1С")
        self.password_edit.setStyleSheet(field_qss)
        self.password_edit.setFont(app_font(13))
        self.password_edit.returnPressed.connect(self._submit)

        fio_label = QLabel("ФИО")
        fio_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        fio_label.setFont(app_font(11, QFont.Weight.DemiBold))
        pwd_label = QLabel("Пароль")
        pwd_label.setStyleSheet("color: rgba(255,255,255,0.65); background: transparent;")
        pwd_label.setFont(app_font(11, QFont.Weight.DemiBold))

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

    def _search_fios(self, query: str) -> list[str]:
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

        self.login_btn.setEnabled(False)
        self.fio_edit.hide_suggestions()
        try:
            result: LoginResult = self._api.login(fio, password)
        except ApiError as exc:
            self.error_label.setText(exc.message)
            if exc.status_code == 503:
                QMessageBox.warning(self, "Сервис недоступен", exc.message)
            return
        finally:
            self.login_btn.setEnabled(True)

        self.fio_edit.hide_suggestions()
        self.logged_in.emit(result)
