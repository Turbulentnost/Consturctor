from __future__ import annotations

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, LoginResult


class LoginWindow(QWidget):
    logged_in = Signal(object)  # LoginResult

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._fio_model = QStringListModel(self)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._refresh_user_list)

        self.setWindowTitle("Constructor — вход")
        self.setMinimumWidth(420)

        title = QLabel("Вход через учётную запись 1С")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSize(14)
        font.setBold(True)
        title.setFont(font)

        subtitle = QLabel("Укажите ФИО и пароль из erp_pm")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet("color: #555;")

        self.fio_combo = QComboBox()
        self.fio_combo.setEditable(True)
        self.fio_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.fio_combo.setModel(self._fio_model)
        self.fio_combo.setPlaceholderText("Начните вводить ФИО…")
        self.fio_combo.lineEdit().textEdited.connect(self._on_fio_edited)
        self.fio_combo.lineEdit().returnPressed.connect(self._submit)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("Пароль 1С")
        self.password_edit.returnPressed.connect(self._submit)

        form = QFormLayout()
        form.addRow("ФИО", self.fio_combo)
        form.addRow("Пароль", self.password_edit)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b00020;")

        self.login_btn = QPushButton("Войти")
        self.login_btn.clicked.connect(self._submit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.login_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addLayout(btn_row)

        QTimer.singleShot(0, self._refresh_user_list)

    def _on_fio_edited(self, _text: str) -> None:
        self._search_timer.start()

    def _refresh_user_list(self) -> None:
        search = self.fio_combo.currentText().strip()
        try:
            items = self._api.search_users(search)
        except ApiError:
            return
        current = self.fio_combo.currentText()
        self._fio_model.setStringList(items)
        self.fio_combo.setEditText(current)

    def _submit(self) -> None:
        fio = self.fio_combo.currentText().strip()
        password = self.password_edit.text()
        self.error_label.setText("")

        if not fio or not password:
            self.error_label.setText("Введите ФИО и пароль")
            return

        self.login_btn.setEnabled(False)
        try:
            result: LoginResult = self._api.login(fio, password)
        except ApiError as exc:
            self.error_label.setText(exc.message)
            if exc.status_code == 503:
                QMessageBox.warning(self, "Сервис недоступен", exc.message)
            return
        finally:
            self.login_btn.setEnabled(True)

        self.logged_in.emit(result)
