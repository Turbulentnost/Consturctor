from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, UserProfile
from app.ui.pages.create_agent_page import CreateAgentPage
from app.ui.pages.kpi_page import KpiPage
from app.ui.pages.my_agents_page import MyAgentsPage
from app.ui.theme import (
    COLOR_CONTENT_BG,
    CONTENT_PADDING_TOP,
    CONTENT_PADDING_X,
    app_font,
)
from app.ui.widgets.sidebar import GlassSidebar
from app.ui.widgets.user_menu import UserMenuHeader


class MainContentWidget(QFrame):
    """Light work area without green border; rounded only on outer right side."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._radius = 28.0

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.0, 0.0, -0.5, -0.5)
        r = self._radius

        path = QPainterPath()
        path.moveTo(rect.left(), rect.top())
        path.lineTo(rect.right() - r, rect.top())
        path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r)
        path.lineTo(rect.right(), rect.bottom() - r)
        path.quadTo(rect.right(), rect.bottom(), rect.right() - r, rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()

        p.fillPath(path, COLOR_CONTENT_BG)
        p.setPen(QPen(QColor(0, 0, 0, 12), 1))
        p.drawPath(path)
        p.end()


class MainShell(QWidget):
    logout_requested = Signal()

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._user: UserProfile | None = None

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

        self._health_label = QLabel("")
        self._health_label.setFont(app_font(12, QFont.Weight.Medium))
        self._health_label.setStyleSheet("color: #2D7A5E; background: transparent;")

        self.user_menu = UserMenuHeader(self)
        self.user_menu.logout_requested.connect(self.logout_requested.emit)
        self.user_menu.settings_requested.connect(self._on_settings)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(18)
        header.addWidget(self._health_label, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        header.addWidget(self.user_menu, 0, Qt.AlignmentFlag.AlignVCenter)

        self._content = MainContentWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(
            CONTENT_PADDING_X,
            CONTENT_PADDING_TOP,
            CONTENT_PADDING_X,
            30,
        )
        content_layout.setSpacing(24)
        content_layout.addLayout(header)
        content_layout.addWidget(self._pages, 1)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar, 0)
        root.addWidget(self._content, 1)

        self.sidebar.set_active_key("create", animate=False)

    def set_user(self, user: UserProfile) -> None:
        self._apply_user(user)
        self.sidebar.set_active_key("create", animate=False)
        self._pages.setCurrentIndex(0)
        QTimer.singleShot(0, self.refresh_health)

    def _apply_user(self, user: UserProfile) -> None:
        self._user = user
        self.user_menu.set_user(fio=user.fio, department=user.department)
        self._load_avatar(user)

    def _load_avatar(self, user: UserProfile) -> None:
        if not user.avatar_url:
            self.user_menu.set_avatar_pixmap(None)
            return
        try:
            data = self._api.fetch_bytes(user.avatar_url)
        except ApiError:
            self.user_menu.set_avatar_pixmap(None)
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self.user_menu.set_avatar_pixmap(None)
            return
        self.user_menu.set_avatar_pixmap(pixmap)

    def refresh_health(self) -> None:
        try:
            health = self._api.health()
            erp = "ERP ok" if health.erp_reachable else "ERP offline"
            self._health_label.setText(f"{health.status} · {erp} · {health.llm_provider}")
            color = "#2D7A5E" if health.erp_reachable else "#A86D22"
            self._health_label.setStyleSheet(f"color: {color}; background: transparent;")
        except ApiError as exc:
            self._health_label.setText(exc.message)
            self._health_label.setStyleSheet("color: #B00020; background: transparent;")

        try:
            profile = self._api.me()
            self._apply_user(profile)
        except ApiError:
            pass

    def _on_settings(self) -> None:
        QMessageBox.information(
            self,
            "Настройки",
            "Раздел настроек профиля появится здесь.\nПока можно сменить аватар позже.",
        )

    def _on_page_changed(self, key: str) -> None:
        idx = self._page_index.get(key, 0)
        self._pages.setCurrentIndex(idx)
