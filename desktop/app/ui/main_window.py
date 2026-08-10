from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, UserProfile


class MainWindow(QWidget):
    def __init__(
        self,
        api: ApiClient,
        user: UserProfile,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._api = api
        self._user = user

        self.setWindowTitle("Constructor")
        self.setMinimumSize(520, 320)

        title = QLabel("Constructor")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft)
        font = title.font()
        font.setPointSize(16)
        font.setBold(True)
        title.setFont(font)

        self.fio_label = QLabel()
        self.dept_label = QLabel()
        self.health_label = QLabel("Проверка связи…")
        self.health_label.setWordWrap(True)

        self.refresh_btn = QPushButton("Обновить статус")
        self.refresh_btn.clicked.connect(self.refresh_health)
        self.logout_btn = QPushButton("Выйти")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.refresh_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.logout_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self.fio_label)
        layout.addWidget(self.dept_label)
        layout.addSpacing(12)
        layout.addWidget(self.health_label)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        self._apply_user(user)
        QTimer.singleShot(0, self.refresh_health)

    def _apply_user(self, user: UserProfile) -> None:
        self._user = user
        self.fio_label.setText(f"Пользователь: {user.fio}")
        dept = user.department.strip() or "не указан"
        self.dept_label.setText(f"Отдел: {dept}")

    def refresh_health(self) -> None:
        try:
            health = self._api.health()
            erp = "доступна" if health.erp_reachable else "недоступна"
            self.health_label.setText(
                f"Backend: {health.status}\n"
                f"ERP ({health.erp_server}): {erp}\n"
                f"LLM: {health.llm_provider}"
            )
            color = "#1b5e20" if health.erp_reachable else "#b26a00"
            self.health_label.setStyleSheet(f"color: {color};")
        except ApiError as exc:
            self.health_label.setText(f"Backend недоступен: {exc.message}")
            self.health_label.setStyleSheet("color: #b00020;")

        try:
            profile = self._api.me()
            self._apply_user(profile)
        except ApiError:
            pass
