from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, UserProfile
from app.ui.pages.create_agent_page import CreateAgentPage
from app.ui.pages.kpi_page import KpiPage
from app.ui.pages.my_agents_page import MyAgentsPage
from app.ui.theme import app_font
from app.ui.widgets.sidebar import SIDEBAR_GREEN, GlassSidebar


class _ShellBackground(QWidget):
    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), SIDEBAR_GREEN)
        p.end()


class ContentPane(QFrame):
    """White content flush to sidebar, with only the outer right corners rounded."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contentPane")
        self._radius = 28.0

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        r = self._radius

        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom() - r)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
        p.fillPath(path, QColor("#ffffff"))

        p.end()


class MainShell(QWidget):
    logout_requested = Signal()

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._user: UserProfile | None = None

        self._bg = _ShellBackground(self)

        self.sidebar = GlassSidebar(self)
        self.sidebar.page_changed.connect(self._on_page_changed)

        self._pages = QStackedWidget()
        self._page_create = CreateAgentPage()
        self._page_agents = MyAgentsPage()
        self._page_kpi = KpiPage()
        self._pages.addWidget(self._page_create)
        self._pages.addWidget(self._page_agents)
        self._pages.addWidget(self._page_kpi)
        self._page_index = {"create": 0, "agents": 1, "kpi": 2}

        self._fio_label = QLabel("—")
        self._fio_label.setFont(app_font(14, QFont.Weight.DemiBold))
        self._fio_label.setStyleSheet("color: #121a17; background: transparent;")

        self._dept_label = QLabel("")
        self._dept_label.setFont(app_font(12))
        self._dept_label.setStyleSheet("color: #5a6b63; background: transparent;")

        self._health_label = QLabel("")
        self._health_label.setFont(app_font(11))
        self._health_label.setStyleSheet("color: #5a6b63; background: transparent;")

        self.logout_btn = QPushButton("Выйти")
        self.logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_btn.setFont(app_font(12, QFont.Weight.DemiBold))
        self.logout_btn.setFixedHeight(36)
        self.logout_btn.setStyleSheet(
            """
            QPushButton {
                background: #0a4a38;
                color: #f5f7f6;
                border: none;
                border-radius: 18px;
                padding: 0 18px;
            }
            QPushButton:hover { background: #0d5c46; }
            QPushButton:pressed { background: #062e24; }
            """
        )
        self.logout_btn.clicked.connect(self.logout_requested.emit)

        header = QHBoxLayout()
        header.setSpacing(16)
        user_col = QVBoxLayout()
        user_col.setSpacing(2)
        user_col.addWidget(self._fio_label)
        user_col.addWidget(self._dept_label)
        header.addLayout(user_col, 1)
        header.addWidget(self._health_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.logout_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        self._content = ContentPane()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(32, 28, 32, 28)
        content_layout.setSpacing(18)
        content_layout.addLayout(header)
        content_layout.addWidget(self._pages, 1)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 14, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar, 0)
        root.addWidget(self._content, 1)

        self.sidebar.set_active_key("create", animate=False)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._bg.setGeometry(self.rect())
        self._bg.lower()

    def set_user(self, user: UserProfile) -> None:
        self._apply_user(user)
        self.sidebar.set_active_key("create", animate=False)
        self._pages.setCurrentIndex(0)
        QTimer.singleShot(0, self.refresh_health)

    def _apply_user(self, user: UserProfile) -> None:
        self._user = user
        self._fio_label.setText(user.fio)
        dept = user.department.strip() or "отдел не указан"
        self._dept_label.setText(dept)

    def refresh_health(self) -> None:
        try:
            health = self._api.health()
            erp = "ERP ok" if health.erp_reachable else "ERP offline"
            self._health_label.setText(f"{health.status} · {erp} · {health.llm_provider}")
            color = "#1b5e20" if health.erp_reachable else "#b26a00"
            self._health_label.setStyleSheet(f"color: {color}; background: transparent;")
        except ApiError as exc:
            self._health_label.setText(exc.message)
            self._health_label.setStyleSheet("color: #b00020; background: transparent;")

        try:
            profile = self._api.me()
            self._apply_user(profile)
        except ApiError:
            pass

    def _on_page_changed(self, key: str) -> None:
        idx = self._page_index.get(key, 0)
        self._pages.setCurrentIndex(idx)
