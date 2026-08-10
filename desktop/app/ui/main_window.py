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
        self._last_run_id: str | None = None

        self.setWindowTitle("Constructor")
        self.setMinimumSize(560, 420)

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

        kpi_title = QLabel("KPI платформы (24ч)")
        kpi_font = kpi_title.font()
        kpi_font.setBold(True)
        kpi_title.setFont(kpi_font)
        self.kpi_label = QLabel("Загрузка KPI…")
        self.kpi_label.setWordWrap(True)
        self.run_label = QLabel("Последний run: —")

        self.refresh_btn = QPushButton("Обновить статус")
        self.refresh_btn.clicked.connect(self.refresh_health)
        self.kpi_btn = QPushButton("Обновить KPI")
        self.kpi_btn.clicked.connect(self.refresh_kpi)
        self.run_btn = QPushButton("Запустить demo run")
        self.run_btn.clicked.connect(self.start_demo_run)
        self.logout_btn = QPushButton("Выйти")

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.refresh_btn)
        btn_row.addWidget(self.kpi_btn)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.logout_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addSpacing(8)
        layout.addWidget(self.fio_label)
        layout.addWidget(self.dept_label)
        layout.addSpacing(12)
        layout.addWidget(self.health_label)
        layout.addSpacing(12)
        layout.addWidget(kpi_title)
        layout.addWidget(self.kpi_label)
        layout.addWidget(self.run_label)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        self._apply_user(user)
        QTimer.singleShot(0, self.refresh_health)
        QTimer.singleShot(0, self.refresh_kpi)

    def _apply_user(self, user: UserProfile) -> None:
        self._user = user
        self.fio_label.setText(f"Пользователь: {user.fio}")
        dept = user.department.strip() or "не указан"
        self.dept_label.setText(f"Отдел: {dept}")

    def refresh_health(self) -> None:
        try:
            health = self._api.health()
            erp = "доступна" if health.erp_reachable else "недоступна"
            lines = [
                f"Backend: {health.status}",
                f"ERP ({health.erp_server}): {erp}",
                f"LLM: {health.llm_provider}",
            ]
            for name, reachable, status in health.platform_services:
                mark = "ok" if reachable else "down"
                lines.append(f"Platform {name}: {mark} ({status})")
            self.health_label.setText("\n".join(lines))
            color = "#1b5e20" if health.status == "ok" else "#b26a00"
            self.health_label.setStyleSheet(f"color: {color};")
        except ApiError as exc:
            self.health_label.setText(f"Backend недоступен: {exc.message}")
            self.health_label.setStyleSheet("color: #b00020;")

        try:
            profile = self._api.me()
            self._apply_user(profile)
        except ApiError:
            pass

    def refresh_kpi(self) -> None:
        try:
            kpi = self._api.kpi_summary()
            keep = (
                f"{kpi.operator_keep_rate * 100:.1f}%"
                if kpi.operator_keep_rate is not None
                else "—"
            )
            self.kpi_label.setText(
                f"Runs: {kpi.total_runs}\n"
                f"Success: {kpi.success_rate * 100:.1f}% | "
                f"Error: {kpi.error_rate * 100:.1f}% | "
                f"HITL: {kpi.hitl_rate * 100:.1f}%\n"
                f"Operator keep rate: {keep}\n"
                f"Tool failures: {kpi.tool_failure_rate * 100:.1f}%"
            )
            self.kpi_label.setStyleSheet("color: #1a237e;")
        except ApiError as exc:
            self.kpi_label.setText(f"KPI недоступен: {exc.message}")
            self.kpi_label.setStyleSheet("color: #b00020;")

    def start_demo_run(self) -> None:
        try:
            run = self._api.start_run("demo-agent", tools=["imap.list_unread", "onec.odata_get"])
            self._last_run_id = run.run_id
            self.run_label.setText(
                f"Последний run: {run.run_id[:8]}… status={run.status} "
                f"events={run.tool_events_count}"
            )
            QTimer.singleShot(1500, self._poll_run)
        except ApiError as exc:
            self.run_label.setText(f"Run error: {exc.message}")

    def _poll_run(self) -> None:
        if not self._last_run_id:
            return
        try:
            run = self._api.get_run(self._last_run_id)
            self.run_label.setText(
                f"Последний run: {run.run_id[:8]}… status={run.status} "
                f"events={run.tool_events_count}"
            )
            if run.status in {"pending", "running"}:
                QTimer.singleShot(1500, self._poll_run)
            else:
                self.refresh_kpi()
        except ApiError as exc:
            self.run_label.setText(f"Run poll error: {exc.message}")
