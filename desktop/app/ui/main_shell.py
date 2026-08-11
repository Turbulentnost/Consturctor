from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, UserProfile
from app.ui.pages.create_agent_page import CreateAgentPage
from app.ui.pages.kpi_page import KpiPage
from app.ui.pages.my_agents_page import MyAgentsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.theme import (
    COLOR_CONTENT_BG,
    CONTENT_PADDING_TOP,
    CONTENT_PADDING_X,
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
        self._avatar_pixmap = QPixmap()

        self.sidebar = GlassSidebar(self)
        self.sidebar.page_changed.connect(self._on_page_changed)
        self.sidebar.collapse_toggled.connect(self._on_sidebar_collapse)

        self._pages = QStackedWidget()
        self._page_create = CreateAgentPage()
        self._page_agents = MyAgentsPage()
        self._page_kpi = KpiPage()
        self._page_settings = SettingsPage(self._api)
        self._pages.addWidget(self._page_create)
        self._pages.addWidget(self._page_agents)
        self._pages.addWidget(self._page_kpi)
        self._pages.addWidget(self._page_settings)
        self._page_index = {"create": 0, "agents": 1, "kpi": 2, "settings": 3}
        self._page_settings.profile_updated.connect(self._on_profile_updated)
        self._page_create.create_regulation_requested.connect(self._on_create_regulation)

        self.user_menu = UserMenuHeader(self)
        self.user_menu.logout_requested.connect(self.logout_requested.emit)
        self.user_menu.settings_requested.connect(self._open_settings)

        self._content = MainContentWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(
            CONTENT_PADDING_X,
            CONTENT_PADDING_TOP,
            CONTENT_PADDING_X,
            30,
        )
        content_layout.setSpacing(0)
        content_layout.addWidget(self._pages, 1)

        # Float profile menu at top-right so page titles can sit higher.
        self.user_menu.setParent(self._content)
        self.user_menu.raise_()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar, 0)
        root.addWidget(self._content, 1)

        self._collapse_btn = QPushButton("‹", self)
        self._collapse_btn.setFixedSize(28, 28)
        self._collapse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._collapse_btn.setToolTip("Свернуть меню")
        self._collapse_btn.setStyleSheet(
            """
            QPushButton {
                color: #EAF7F3;
                background: rgba(6, 40, 34, 0.94);
                border: 1px solid rgba(255,255,255,0.18);
                border-radius: 14px;
                font-size: 18px;
            }
            QPushButton:hover { background: rgba(8, 70, 58, 0.98); }
            """
        )
        self._collapse_btn.clicked.connect(self.sidebar.toggle_collapsed)

        self.sidebar.set_active_key("create", animate=False)
        QTimer.singleShot(0, self._position_overlays)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_overlays()

    def _position_overlays(self) -> None:
        self._position_collapse_btn()
        self._position_user_menu()

    def _position_collapse_btn(self) -> None:
        btn = self._collapse_btn
        if self.sidebar.is_collapsed():
            x = (self.sidebar.width() - btn.width()) // 2
        else:
            # Bottom-right inside the left menu, not crossing into the content pane.
            x = self.sidebar.width() - btn.width() - 12
        y = self.height() - btn.height() - 22
        btn.move(max(0, x), max(0, y))
        btn.raise_()

    def _position_user_menu(self) -> None:
        menu = self.user_menu
        menu.adjustSize()
        x = self._content.width() - menu.width() - CONTENT_PADDING_X
        y = CONTENT_PADDING_TOP
        menu.move(max(0, x), max(0, y))
        menu.raise_()

    def _on_sidebar_collapse(self, collapsed: bool) -> None:
        self._collapse_btn.setText("›" if collapsed else "‹")
        self._collapse_btn.setToolTip("Развернуть меню" if collapsed else "Свернуть меню")
        QTimer.singleShot(0, self._position_overlays)

    def set_user(self, user: UserProfile) -> None:
        self._apply_user(user)
        self.sidebar.set_active_key("create", animate=False)
        self._pages.setCurrentIndex(0)
        QTimer.singleShot(0, self._refresh_profile)

    def _apply_user(self, user: UserProfile) -> None:
        self._user = user
        self.user_menu.set_user(fio=user.fio, department=user.department)
        self._load_avatar(user)
        pixmap = None if self._avatar_pixmap.isNull() else self._avatar_pixmap
        self._page_settings.set_user(user, pixmap)

    def _load_avatar(self, user: UserProfile) -> None:
        if not user.avatar_url:
            self._avatar_pixmap = QPixmap()
            self.user_menu.set_avatar_pixmap(None)
            return
        try:
            data = self._api.fetch_bytes(user.avatar_url)
        except ApiError:
            self._avatar_pixmap = QPixmap()
            self.user_menu.set_avatar_pixmap(None)
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            self._avatar_pixmap = QPixmap()
            self.user_menu.set_avatar_pixmap(None)
            return
        self._avatar_pixmap = pixmap
        self.user_menu.set_avatar_pixmap(pixmap)

    def _refresh_profile(self) -> None:
        try:
            profile = self._api.me()
            self._apply_user(profile)
        except ApiError:
            pass

    def _open_settings(self) -> None:
        if self._user is not None:
            pixmap = None if self._avatar_pixmap.isNull() else self._avatar_pixmap
            self._page_settings.set_user(self._user, pixmap)
        self._pages.setCurrentIndex(self._page_index["settings"])

    def _on_profile_updated(self, user: object) -> None:
        if isinstance(user, UserProfile):
            self._apply_user(user)

    def _on_create_regulation(self) -> None:
        QMessageBox.information(
            self,
            "Создать регламент",
            "Мастер создания регламента с ИИ появится здесь.",
        )

    def _on_page_changed(self, key: str) -> None:
        idx = self._page_index.get(key)
        if idx is None:
            return
        self._pages.setCurrentIndex(idx)
