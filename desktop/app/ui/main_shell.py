from __future__ import annotations

from threading import Thread

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.api_client import ApiClient, ApiError, RegulationParseResult, RoleMatchResult, UserProfile
from app.ui.pages.create_agent_page import CreateAgentPage
from app.ui.pages.kpi_page import KpiPage
from app.ui.pages.my_agents_page import MyAgentsPage
from app.ui.pages.regulation_review_page import RegulationReviewPage
from app.ui.pages.role_match_page import RoleMatchPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.theme import (
    COLOR_CONTENT_MUTED,
    COLOR_CONTENT_BG,
    CONTENT_PADDING_TOP,
    CONTENT_PADDING_X,
    MAIN_TEXT,
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


class LoadingPage(QWidget):
    """Simple full-page progress state for long backend analysis steps."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = QLabel("Идёт анализ")
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setFont(app_font(28, QFont.Weight.DemiBold))
        self._title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")

        self._subtitle = QLabel("")
        self._subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._subtitle.setWordWrap(True)
        self._subtitle.setFont(app_font(14))
        self._subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")

        progress = QProgressBar()
        progress.setRange(0, 0)
        progress.setTextVisible(False)
        progress.setFixedSize(320, 8)
        progress.setStyleSheet(
            """
            QProgressBar {
                background: rgba(6,72,61,0.12);
                border: none;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background: #08745F;
                border-radius: 4px;
            }
            """
        )

        progress_row = QHBoxLayout()
        progress_row.addStretch(1)
        progress_row.addWidget(progress)
        progress_row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 48, 48, 48)
        layout.addStretch(1)
        layout.addWidget(self._title)
        layout.addSpacing(10)
        layout.addWidget(self._subtitle)
        layout.addSpacing(26)
        layout.addLayout(progress_row)
        layout.addStretch(1)

    def set_message(self, title: str, subtitle: str) -> None:
        self._title.setText(title)
        self._subtitle.setText(subtitle)


class MainShell(QWidget):
    logout_requested = Signal()
    _regulation_ready = Signal(object)
    _regulation_failed = Signal(str)
    _role_match_ready = Signal(object)
    _role_match_failed = Signal(str)

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
        self._page_review = RegulationReviewPage()
        self._page_role_match = RoleMatchPage()
        self._page_loading = LoadingPage()
        self._pages.addWidget(self._page_create)
        self._pages.addWidget(self._page_agents)
        self._pages.addWidget(self._page_kpi)
        self._pages.addWidget(self._page_settings)
        self._pages.addWidget(self._page_review)
        self._pages.addWidget(self._page_role_match)
        self._pages.addWidget(self._page_loading)
        self._page_index = {
            "create": 0,
            "agents": 1,
            "kpi": 2,
            "settings": 3,
            "review": 4,
            "role_match": 5,
            "loading": 6,
        }
        self._page_settings.profile_updated.connect(self._on_profile_updated)
        self._page_create.create_regulation_requested.connect(self._on_create_regulation)
        self._page_create.regulation_selected.connect(self._on_regulation_selected)
        self._page_review.back_requested.connect(self._back_to_create)
        self._page_review.continue_requested.connect(self._on_continue_after_review)
        self._page_review.fullscreen_changed.connect(self._on_review_fullscreen)
        self._page_role_match.back_requested.connect(self._back_to_review)
        self._page_role_match.finish_requested.connect(self._on_finish_role_match)
        self._page_role_match.decision_requested.connect(self._on_role_match_decision)
        self._regulation_ready.connect(self._show_regulation_result)
        self._regulation_failed.connect(self._show_regulation_error)
        self._role_match_ready.connect(self._show_role_match_result)
        self._role_match_failed.connect(self._show_role_match_error)
        self._pages.currentChanged.connect(self._on_stack_changed)
        self._review_fullscreen = False
        self._current_regulation: RegulationParseResult | None = None
        self._current_role_match: RoleMatchResult | None = None

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

        # Header chrome: expand (review only) + profile, top-right.
        self._expand_btn = QPushButton("⛶", self._content)
        self._expand_btn.setFixedSize(36, 36)
        self._expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._expand_btn.setToolTip("На весь экран")
        self._expand_btn.setStyleSheet(
            """
            QPushButton {
                background: #EEF7F3;
                color: #06483D;
                border: none;
                border-radius: 18px;
                font-size: 16px;
            }
            QPushButton:hover { background: #DFF5EC; }
            """
        )
        self._expand_btn.hide()
        self._expand_btn.clicked.connect(self._page_review.toggle_fullscreen)

        self.user_menu.setParent(self._content)
        self._expand_btn.raise_()
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
        right = self._content.width() - CONTENT_PADDING_X
        y = CONTENT_PADDING_TOP
        menu_x = right - menu.width()
        menu.move(max(0, menu_x), max(0, y))
        if self._expand_btn.isVisible():
            btn_y = y + max(0, (menu.height() - self._expand_btn.height()) // 2)
            btn_x = menu_x - self._expand_btn.width() - 10
            self._expand_btn.move(max(0, btn_x), max(0, btn_y))
            self._expand_btn.raise_()
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

    def _on_regulation_selected(self, path: str) -> None:
        self._page_create.set_processing(True)

        def run() -> None:
            try:
                result = self._api.upload_regulation(path)
            except ApiError as exc:
                self._regulation_failed.emit(exc.message)
                return
            self._regulation_ready.emit(result)

        Thread(target=run, daemon=True).start()

    def _show_regulation_result(self, result: object) -> None:
        self._page_create.set_processing(False)
        if not isinstance(result, RegulationParseResult):
            return
        self._current_regulation = result
        self._current_role_match = None
        self._page_review.set_result(result)
        self._pages.setCurrentIndex(self._page_index["review"])

    def _show_regulation_error(self, message: str) -> None:
        self._page_create.set_processing(False)
        QMessageBox.warning(self, "Распознавание регламента", message)

    def _back_to_create(self) -> None:
        self._page_review.set_fullscreen(False)
        self._pages.setCurrentIndex(self._page_index["create"])

    def _on_continue_after_review(self) -> None:
        if self._current_regulation is None:
            return
        default_department = self._user.department if self._user is not None else ""
        position = (self._user.position if self._user is not None else "").strip()
        if not position:
            position, ok = QInputDialog.getText(
                self,
                "Выбор должности",
                "Должность не найдена в 1С. Укажите должность для поиска фрагментов:",
            )
            position = position.strip()
            if not ok or not position:
                return
        self._page_loading.set_message(
            "Анализируем функции должности",
            (
                f"Ищем фрагменты регламента для должности «{position}». "
                "Это может занять несколько минут."
            ),
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                result = self._api.create_role_matches(
                    self._current_regulation.regulation_id,
                    position=position,
                    department=default_department,
                )
            except ApiError as exc:
                self._role_match_failed.emit(exc.message)
                return
            self._role_match_ready.emit(result)

        Thread(target=run, daemon=True).start()

    def _show_role_match_result(self, result: object) -> None:
        if not isinstance(result, RoleMatchResult):
            return
        self._current_role_match = result
        self._page_role_match.set_result(result, self._current_regulation)
        self._pages.setCurrentIndex(self._page_index["role_match"])

    def _show_role_match_error(self, message: str) -> None:
        if self._pages.currentIndex() == self._page_index["loading"]:
            self._pages.setCurrentIndex(self._page_index["review"])
        QMessageBox.warning(self, "Поиск фрагментов по должности", message)

    def _back_to_review(self) -> None:
        self._pages.setCurrentIndex(self._page_index["review"])

    def _on_finish_role_match(self) -> None:
        QMessageBox.information(
            self,
            "Связь с должностью",
            "Подтверждённые фрагменты сохранены.",
        )

    def _on_role_match_decision(self, match_id: str, status: str) -> None:
        if self._current_regulation is None or self._current_role_match is None:
            return

        def run() -> None:
            try:
                result = self._api.decide_role_match(
                    self._current_regulation.regulation_id,
                    self._current_role_match.run_id,
                    match_id,
                    status,
                )
            except ApiError as exc:
                self._role_match_failed.emit(exc.message)
                return
            self._role_match_ready.emit(result)

        Thread(target=run, daemon=True).start()

    def _on_review_fullscreen(self, enabled: bool) -> None:
        self._review_fullscreen = enabled
        self.sidebar.setVisible(not enabled)
        self._collapse_btn.setVisible(not enabled)
        self._expand_btn.setText("⧉" if enabled else "⛶")
        self._expand_btn.setToolTip("Свернуть" if enabled else "На весь экран")
        content_layout = self._content.layout()
        if isinstance(content_layout, QVBoxLayout):
            if enabled:
                content_layout.setContentsMargins(20, 20, 20, 20)
            else:
                content_layout.setContentsMargins(
                    CONTENT_PADDING_X,
                    CONTENT_PADDING_TOP,
                    CONTENT_PADDING_X,
                    30,
                )
        QTimer.singleShot(0, self._position_overlays)

    def _set_expand_visible(self, visible: bool) -> None:
        self._expand_btn.setVisible(visible)
        QTimer.singleShot(0, self._position_overlays)

    def _on_stack_changed(self, index: int) -> None:
        on_review = index == self._page_index["review"]
        if not on_review and self._review_fullscreen:
            self._page_review.set_fullscreen(False)
        self._set_expand_visible(on_review)

    def _on_page_changed(self, key: str) -> None:
        if self._review_fullscreen:
            self._page_review.set_fullscreen(False)
        idx = self._page_index.get(key)
        if idx is None:
            return
        self._pages.setCurrentIndex(idx)
