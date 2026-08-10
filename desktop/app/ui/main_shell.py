from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
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
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(14, 18, -14, -18)
        path = QPainterPath()
        path.addRoundedRect(rect, 28, 28)

        grad = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
        grad.setColorAt(0.0, QColor("#0f7a59"))
        grad.setColorAt(0.38, SIDEBAR_GREEN)
        grad.setColorAt(1.0, QColor("#01100d"))
        p.fillPath(path, grad)

        glow = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top())
        glow.setColorAt(0.0, QColor(145, 255, 213, 34))
        glow.setColorAt(0.5, QColor(145, 255, 213, 8))
        glow.setColorAt(1.0, QColor(255, 255, 255, 22))
        p.fillPath(path, glow)

        p.setPen(QPen(QColor(255, 255, 255, 35), 1))
        p.drawPath(path)
        p.end()


class ContentPane(QFrame):
    """White work area inside the dark rounded shell."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("contentPane")
        self._radius = 24.0

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        r = self._radius

        path = QPainterPath()
        path.moveTo(rect.left() + r, rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom() - r)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.lineTo(rect.left(), rect.top() + r)
        path.quadTo(rect.left(), rect.top(), rect.left() + r, rect.top())
        path.closeSubpath()
        p.fillPath(path, QColor("#ffffff"))
        p.setPen(QPen(QColor(0, 0, 0, 18), 1))
        p.drawPath(path)

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
        self._fio_label.setFont(app_font(13, QFont.Weight.DemiBold))
        self._fio_label.setStyleSheet("color: #121a17; background: transparent;")

        self._dept_label = QLabel("")
        self._dept_label.setFont(app_font(11))
        self._dept_label.setStyleSheet("color: #5a6b63; background: transparent;")

        self._health_label = QLabel("")
        self._health_label.setFont(app_font(11))
        self._health_label.setStyleSheet("color: #5a6b63; background: transparent;")

        self.logout_btn = QPushButton("Выйти")
        self.logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.logout_btn.setFont(app_font(11, QFont.Weight.DemiBold))
        self.logout_btn.setFixedHeight(30)
        self.logout_btn.setStyleSheet(
            """
            QPushButton {
                background: #0a4a38;
                color: #f5f7f6;
                border: none;
                border-radius: 15px;
                padding: 0 14px;
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
        content_layout.setContentsMargins(28, 22, 28, 26)
        content_layout.setSpacing(16)
        content_layout.addLayout(header)
        content_layout.addWidget(self._pages, 1)

        root = QHBoxLayout(self)
        root.setContentsMargins(10, 22, 22, 22)
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
