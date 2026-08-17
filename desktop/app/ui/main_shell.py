from __future__ import annotations

from pathlib import Path
from threading import Thread

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
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

from app.attachment_text import format_attachments_block
from app.api_client import (
    AgentReadinessResult,
    ApiClient,
    ApiError,
    PassportSession,
    RegulationParseResult,
    RegulationRevisionResult,
    RoleMatchResult,
    AgentDraft,
    AgentSuggestion,
    QuestionChatMessage,
    QuestionChatSession,
    RegulationCreationMessage,
    RegulationCreationSession,
    UserProfile,
    WorkflowListItem,
    WorkflowRecord,
)
from app.ui.pages.agent_passport_page import AgentPassportPage
from app.ui.pages.agent_implementation_page import AgentImplementationPage
from app.ui.pages.agent_run_page import AgentRunPage
from app.ui.pages.create_agent_page import CreateAgentPage
from app.ui.pages.kpi_page import KpiPage
from app.ui.pages.my_agents_page import MyAgentsPage
from app.ui.pages.regulation_review_page import RegulationReviewPage
from app.ui.pages.regulation_creation_page import RegulationCreationPage
from app.ui.pages.readiness_page import ReadinessPage
from app.ui.pages.revision_result_page import RevisionResultPage
from app.ui.pages.role_match_page import RoleMatchPage
from app.ui.pages.saved_workflows_page import SavedWorkflowsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.workflow_page import WorkflowPage
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
    _readiness_ready = Signal(object)
    _readiness_failed = Signal(str)
    _revision_ready = Signal(object)
    _draft_ready = Signal(object)
    _drafts_ready = Signal(object)
    _agents_table_ready = Signal(object)
    _implementation_agents_ready = Signal(object)
    _passport_ready = Signal(object)
    _passport_failed = Signal(str)
    _published_agent_ready = Signal(object)
    _chat_ready = Signal(object)
    _creation_session_ready = Signal(object)
    _creation_stream_event = Signal(str, str)

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
        self._page_implementation_agents = AgentImplementationPage()
        self._page_workflows = WorkflowPage(self._api)
        self._page_agent_run = AgentRunPage(self._api)
        self._page_saved_workflows = SavedWorkflowsPage(self._api)
        self._page_kpi = KpiPage()
        self._page_settings = SettingsPage(self._api)
        self._page_review = RegulationReviewPage()
        self._page_role_match = RoleMatchPage()
        self._page_readiness = ReadinessPage()
        self._page_revision = RevisionResultPage(self._api)
        self._page_creation_chat = RegulationCreationPage()
        self._page_passport = AgentPassportPage()
        self._page_loading = LoadingPage()
        self._pages.addWidget(self._page_create)
        self._pages.addWidget(self._page_agents)
        self._pages.addWidget(self._page_implementation_agents)
        self._pages.addWidget(self._page_workflows)
        self._pages.addWidget(self._page_agent_run)
        self._pages.addWidget(self._page_saved_workflows)
        self._pages.addWidget(self._page_kpi)
        self._pages.addWidget(self._page_settings)
        self._pages.addWidget(self._page_review)
        self._pages.addWidget(self._page_role_match)
        self._pages.addWidget(self._page_readiness)
        self._pages.addWidget(self._page_revision)
        self._pages.addWidget(self._page_creation_chat)
        self._pages.addWidget(self._page_passport)
        self._pages.addWidget(self._page_loading)
        self._page_index = {
            "create": 0,
            "agents": 1,
            "implementation_agents": 2,
            "workflows": 3,
            "agent_run": 4,
            "saved_workflows": 5,
            "kpi": 6,
            "settings": 7,
            "review": 8,
            "role_match": 9,
            "readiness": 10,
            "revision": 11,
            "creation_chat": 12,
            "passport": 13,
            "loading": 14,
        }
        self._page_workflows.saved.connect(lambda _id: self._page_saved_workflows.refresh())
        self._page_workflows.saved_record.connect(self._on_workflow_record_saved)
        self._page_workflows.launch_requested.connect(self._on_launch_workflow_agent)
        self._page_saved_workflows.open_requested.connect(self._on_open_saved_workflow)
        self._page_implementation_agents.create_requested.connect(self._on_create_agent_from_inline_suggestion)
        self._page_settings.profile_updated.connect(self._on_profile_updated)
        self._page_agents.continue_requested.connect(self._on_continue_agent_draft)
        self._page_agents.create_requested.connect(self._on_create_agent_from_suggestion)
        self._page_agents.create_suggestion_requested.connect(self._on_create_agent_from_draft_suggestion)
        self._page_agents.delete_requested.connect(self._on_delete_agent_draft)
        self._page_agents.delete_suggestion_requested.connect(self._on_delete_agent_suggestion)
        self._page_agents.delete_agent_requested.connect(self._on_delete_published_agent)
        self._page_agents.run_agent_requested.connect(self._on_run_published_agent)
        self._page_passport.back_requested.connect(lambda: self._pages.setCurrentIndex(self._page_index["agents"]))
        self._page_passport.draft_requested.connect(self._on_passport_draft_requested)
        self._page_passport.answer_requested.connect(self._on_passport_answer_requested)
        self._page_passport.finished_requested.connect(self._on_passport_finished)
        self._page_create.create_regulation_requested.connect(self._on_create_regulation)
        self._page_create.regulation_selected.connect(self._on_regulation_selected)
        self._page_review.back_requested.connect(self._back_to_create)
        self._page_review.continue_requested.connect(self._on_continue_after_review)
        self._page_review.fullscreen_changed.connect(self._on_review_fullscreen)
        self._page_role_match.back_requested.connect(self._back_to_review)
        self._page_role_match.finish_requested.connect(self._on_finish_role_match)
        self._page_role_match.decision_requested.connect(self._on_role_match_decision)
        self._page_readiness.back_requested.connect(lambda: self._pages.setCurrentIndex(self._page_index["role_match"]))
        self._page_readiness.chat_requested.connect(self._on_open_question_chat)
        self._page_readiness.chat_message_requested.connect(self._on_send_question_chat_message)
        self._page_readiness.answer_requested.connect(self._on_readiness_answer)
        self._page_readiness.change_decision_requested.connect(self._on_readiness_change_decision)
        self._page_readiness.finalize_requested.connect(self._on_readiness_finalize)
        self._page_readiness.skip_to_agents_requested.connect(self._on_skip_readiness_to_agents)
        self._page_readiness.supplement_requested.connect(self._on_start_readiness_supplement)
        self._page_revision.download_requested.connect(self._on_revision_download)
        self._page_revision.next_requested.connect(self._on_revision_next)
        self._page_creation_chat.message_requested.connect(self._on_regulation_creation_message)
        self._page_creation_chat.finished_requested.connect(self._show_regulation_result)
        self._regulation_ready.connect(self._show_regulation_result)
        self._regulation_failed.connect(self._show_regulation_error)
        self._role_match_ready.connect(self._show_role_match_result)
        self._role_match_failed.connect(self._show_role_match_error)
        self._readiness_ready.connect(self._show_readiness_result)
        self._readiness_failed.connect(self._show_readiness_error)
        self._revision_ready.connect(self._show_revision_result)
        self._draft_ready.connect(self._show_draft_result)
        self._drafts_ready.connect(self._show_drafts_result)
        self._agents_table_ready.connect(self._show_agents_table_result)
        self._implementation_agents_ready.connect(self._show_implementation_agents)
        self._passport_ready.connect(self._show_passport_result)
        self._passport_failed.connect(self._show_passport_error)
        self._published_agent_ready.connect(self._on_launch_workflow_agent)
        self._chat_ready.connect(self._show_chat_result)
        self._creation_session_ready.connect(self._show_creation_session)
        self._creation_stream_event.connect(self._page_creation_chat.append_stream_event)
        self._pages.currentChanged.connect(self._on_stack_changed)
        self._review_fullscreen = False
        self._current_regulation: RegulationParseResult | None = None
        self._current_role_match: RoleMatchResult | None = None
        self._current_readiness: AgentReadinessResult | None = None
        self._current_draft: AgentDraft | None = None
        self._current_chat: QuestionChatSession | None = None
        self._current_creation_session: RegulationCreationSession | None = None
        self._current_revision: RegulationRevisionResult | None = None
        self._implementation_draft_id = ""
        self._current_passport_draft_id = ""
        self._current_passport_agent_id = ""
        self._auto_finalize_running = False
        self._supplement_in_progress = False

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
        self.user_menu.set_user(fio=user.fio, position=user.position)
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
        self._page_loading.set_message(
            "Создаём чат регламента",
            "Готовим профиль стиля и первый вопрос.",
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                session = self._api.start_regulation_creation()
            except ApiError as exc:
                self._regulation_failed.emit(exc.message)
                return
            self._creation_session_ready.emit(session)

        Thread(target=run, daemon=True).start()

    def _on_regulation_creation_message(self, draft_id: str, message: str, file_paths: list | None = None) -> None:
        paths = [str(path) for path in (file_paths or []) if str(path).strip()]
        names = [Path(path).name for path in paths]
        display = message.strip()
        if names:
            note = "📎 " + ", ".join(names)
            display = f"{display}\n\n{note}".strip() if display else note
        if self._current_creation_session is not None:
            from dataclasses import replace

            pending = RegulationCreationMessage(
                message_id="local-pending",
                draft_id=draft_id,
                role="user",
                content=display or message,
                structured={"attachments": [{"name": name} for name in names]} if names else {},
            )
            self._page_creation_chat.set_session(
                replace(
                    self._current_creation_session,
                    status="generating",
                    messages=[*self._current_creation_session.messages, pending],
                )
            )

        def run() -> None:
            try:
                session = self._api.stream_regulation_creation_message(
                    draft_id,
                    message,
                    lambda event_type, text: self._creation_stream_event.emit(event_type, text),
                    file_paths=paths,
                )
            except ApiError as exc:
                self._regulation_failed.emit(exc.message)
                return
            self._creation_session_ready.emit(session)

        Thread(target=run, daemon=True).start()

    def _show_creation_session(self, session: object) -> None:
        if not isinstance(session, RegulationCreationSession):
            return
        self._current_creation_session = session
        # Сначала показать страницу, потом наполнить — меньше риска layout-шторма на скрытом виджете.
        self._pages.setCurrentIndex(self._page_index["creation_chat"])
        self._page_creation_chat.set_session(session)

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
        QMessageBox.warning(self, "Создание регламента", message)

    def _back_to_create(self) -> None:
        self._page_review.set_fullscreen(False)
        self._pages.setCurrentIndex(self._page_index["create"])

    def _on_continue_after_review(self) -> None:
        if self._current_regulation is None:
            return
        position = (self._user.position if self._user is not None else "").strip()
        department = (self._user.department if self._user is not None else "").strip()
        if not position:
            position, ok = QInputDialog.getText(
                self,
                "Выбор должности",
                "Должность не найдена в профиле. Укажите должность для поиска фрагментов:",
            )
            position = position.strip()
            if not ok or not position:
                return
        if not department:
            department, ok = QInputDialog.getText(
                self,
                "Выбор подразделения",
                "Подразделение не найдено в профиле. Укажите подразделение для поиска фрагментов:",
            )
            department = department.strip()
            if not ok or not department:
                return
        self._page_loading.set_message(
            "Cursor Agent выделяет функциональные блоки",
            (
                "Передаём полный распознанный регламент агенту, чтобы выделить "
                "связанные бизнес-функции и вопросы для оптимизации. "
                "Это может занять несколько минут."
            ),
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                result = self._api.extract_regulation_functions(
                    self._current_regulation.regulation_id,
                    position=position,
                    department=department,
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
        if self._current_regulation is None or self._current_role_match is None:
            return
        self._page_loading.set_message(
            "Создаём черновик ИИ-агента",
            "Сохраняем подтверждённые функции и готовим чат-вопросы для уточнения регламента.",
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                draft = self._api.create_agent_draft(
                    self._current_regulation.regulation_id,
                    self._current_role_match.run_id,
                )
                draft = self._api.ensure_draft_readiness(draft.draft_id)
                readiness = draft.readiness
                if readiness is None or not any(not question.answered for question in readiness.questions):
                    draft = self._api.update_agent_draft_status(draft.draft_id, "ready")
                    workflows = self._api.list_workflows()
                    suggestions = draft.agent_suggestions or _suggestions_from_role_match(self._current_role_match)
                    self._implementation_agents_ready.emit((suggestions, workflows, draft.draft_id))
                    return
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._draft_ready.emit((draft, None, "choice"))

        Thread(target=run, daemon=True).start()

    def _first_chat_for_draft(self, draft: AgentDraft) -> QuestionChatSession | None:
        readiness = draft.readiness
        if readiness is None:
            return None
        question = next((item for item in readiness.questions if not item.answered), None)
        try:
            latest = self._api.latest_question_chat(draft.draft_id)
        except ApiError:
            latest = None
        if latest is not None:
            if latest.status != "answered":
                return latest
            if question is None:
                return latest
        if question is None:
            return None
        return self._api.create_question_chat(draft.draft_id, question.question_id)

    def _show_draft_result(self, payload: object) -> None:
        mode = ""
        if isinstance(payload, tuple):
            draft = payload[0] if len(payload) >= 1 else None
            chat = payload[1] if len(payload) >= 2 else None
            mode = str(payload[2]) if len(payload) >= 3 else ""
        else:
            draft, chat = payload, None
        if not isinstance(draft, AgentDraft):
            return
        self._current_draft = draft
        self._current_readiness = draft.readiness
        self._current_chat = chat if isinstance(chat, QuestionChatSession) else None
        if draft.readiness is not None:
            self._page_readiness.set_result(draft.readiness)
        self._page_readiness.set_supplement_choice(mode == "choice")
        self._page_readiness.set_chat(self._current_chat)
        self._pages.setCurrentIndex(self._page_index["readiness"])
        if mode != "choice" and self._supplement_in_progress and self._readiness_complete_with_changes():
            self._finalize_supplement_revision()

    def _show_readiness_result(self, result: object) -> None:
        if not isinstance(result, AgentReadinessResult):
            return
        self._current_readiness = result
        self._page_readiness.set_result(result)
        self._page_readiness.set_supplement_choice(False)
        self._pages.setCurrentIndex(self._page_index["readiness"])
        if self._supplement_in_progress and self._readiness_complete_with_changes():
            self._finalize_supplement_revision()

    def _show_chat_result(self, result: object) -> None:
        if not isinstance(result, QuestionChatSession):
            return
        self._current_chat = result
        self._page_readiness.set_chat(result)

    def _show_readiness_error(self, message: str) -> None:
        self._pages.setCurrentIndex(self._page_index["role_match"])
        QMessageBox.warning(self, "Готовность регламента", message)

    def _on_readiness_answer(self, question_id: str, answer: str) -> None:
        if self._current_readiness is None or not answer.strip():
            return

        def run() -> None:
            try:
                result = self._api.answer_readiness_question(
                    self._active_readiness_regulation_id(),
                    self._current_readiness.readiness_run_id,
                    question_id,
                    answer,
                )
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._readiness_ready.emit(result)

        Thread(target=run, daemon=True).start()

    def _on_open_question_chat(self, question_id: str) -> None:
        if self._current_draft is None:
            return

        def run() -> None:
            try:
                chat = self._api.create_question_chat(self._current_draft.draft_id, question_id)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._chat_ready.emit(chat)

        Thread(target=run, daemon=True).start()

    def _on_skip_readiness_to_agents(self) -> None:
        if self._current_draft is None:
            return
        self._page_loading.set_message(
            "Готовим ИИ-агента",
            "Сохраняем подтверждённые функции без изменения регламента.",
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                draft = self._api.update_agent_draft_status(self._current_draft.draft_id, "ready")
                workflows = self._api.list_workflows()
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            suggestions = draft.agent_suggestions or _suggestions_from_role_match(self._current_role_match)
            self._implementation_agents_ready.emit((suggestions, workflows, draft.draft_id))

        Thread(target=run, daemon=True).start()

    def _on_start_readiness_supplement(self) -> None:
        if self._current_draft is None:
            return
        self._supplement_in_progress = True
        self._page_readiness.set_supplement_choice(False)

        def run() -> None:
            try:
                draft = self._api.get_agent_draft(self._current_draft.draft_id)
                chat = self._first_chat_for_draft(draft)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._draft_ready.emit((draft, chat, "supplement"))

        Thread(target=run, daemon=True).start()

    def _on_send_question_chat_message(self, question_id: str, message: str) -> None:
        if self._current_draft is None or not message.strip():
            return
        self._show_pending_chat_message(question_id, message.strip())

        def run() -> None:
            try:
                chat = self._api.send_question_chat_message(
                    self._current_draft.draft_id,
                    question_id,
                    message,
                )
                draft = self._api.get_agent_draft(self._current_draft.draft_id)
                # Backend после ответа уже может вернуть чат следующего вопроса.
                # Если всё ещё answered — дотягиваем следующий явно.
                if chat.status == "answered":
                    chat = self._first_chat_for_draft(draft) or chat
                elif draft.readiness is not None:
                    next_q = next(
                        (item for item in draft.readiness.questions if not item.answered),
                        None,
                    )
                    if next_q is not None and chat.question_id != next_q.question_id:
                        chat = self._first_chat_for_draft(draft) or chat
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._draft_ready.emit((draft, chat))

        Thread(target=run, daemon=True).start()

    def _show_pending_chat_message(self, question_id: str, message: str) -> None:
        if self._current_chat is None:
            return
        if question_id != self._current_chat.question_id:
            return
        pending = QuestionChatSession(
            session_id=self._current_chat.session_id,
            draft_id=self._current_chat.draft_id,
            readiness_run_id=self._current_chat.readiness_run_id,
            question_id=self._current_chat.question_id,
            function_id=self._current_chat.function_id,
            target_field=self._current_chat.target_field,
            status="generating",
            context=self._current_chat.context,
            messages=[
                *self._current_chat.messages,
                QuestionChatMessage(
                    message_id="local-user-pending",
                    session_id=self._current_chat.session_id,
                    role="user",
                    content=message,
                    structured={},
                ),
                QuestionChatMessage(
                    message_id="local-assistant-generating",
                    session_id=self._current_chat.session_id,
                    role="assistant",
                    content="Задаю вопрос ...",
                    structured={"isGenerating": True, "quickAnswers": []},
                ),
            ],
        )
        self._current_chat = pending
        self._page_readiness.set_chat(pending)

    def _on_readiness_change_decision(self, change_id: str, status: str, after: str) -> None:
        if self._current_readiness is None:
            return
        regulation_id = self._active_readiness_regulation_id()

        def run() -> None:
            try:
                result = self._api.update_readiness_change(
                    regulation_id,
                    self._current_readiness.readiness_run_id,
                    change_id,
                    status,
                    after,
                )
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._readiness_ready.emit(result)

        Thread(target=run, daemon=True).start()

    def _on_readiness_finalize(self) -> None:
        if self._current_readiness is None:
            return
        regulation_id = self._active_readiness_regulation_id()
        self._page_loading.set_message(
            "Создаём копию регламента",
            "Применяем подтверждённые изменения и формируем протокол.",
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                result = self._api.finalize_readiness(
                    regulation_id,
                    self._current_readiness.readiness_run_id,
                )
            except ApiError as exc:
                self._auto_finalize_running = False
                self._readiness_failed.emit(exc.message)
                return
            self._auto_finalize_running = False
            self._revision_ready.emit(result)

        Thread(target=run, daemon=True).start()

    def _active_readiness_regulation_id(self) -> str:
        if self._current_readiness is not None and self._current_readiness.regulation_id:
            return self._current_readiness.regulation_id
        if self._current_draft is not None and self._current_draft.regulation_id:
            return self._current_draft.regulation_id
        if self._current_regulation is not None:
            return self._current_regulation.regulation_id
        return ""

    def _maybe_auto_finalize_readiness(self) -> None:
        readiness = self._current_readiness
        if readiness is None or self._auto_finalize_running or readiness.status == "finalized":
            return
        if not readiness.changes:
            return
        if any(not question.answered for question in readiness.questions):
            return
        self._auto_finalize_running = True
        self._on_readiness_finalize()

    def _readiness_complete_with_changes(self) -> bool:
        readiness = self._current_readiness
        if readiness is None:
            return False
        if any(not question.answered for question in readiness.questions):
            return False
        return bool(readiness.changes)

    def _finalize_supplement_revision(self) -> None:
        if self._current_readiness is None or self._current_draft is None or self._auto_finalize_running:
            return
        regulation_id = self._active_readiness_regulation_id()
        readiness_run_id = self._current_readiness.readiness_run_id
        self._auto_finalize_running = True
        self._page_loading.set_message(
            "Дополняем регламент",
            "Формируем новую редакцию документа.",
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                result = self._api.finalize_readiness(regulation_id, readiness_run_id)
            except ApiError as exc:
                self._auto_finalize_running = False
                self._readiness_failed.emit(exc.message)
                return
            self._auto_finalize_running = False
            self._revision_ready.emit(result)

        Thread(target=run, daemon=True).start()

    def _on_revision_next(self) -> None:
        if self._current_draft is None:
            return
        draft_id = self._current_draft.draft_id
        self._page_loading.set_message(
            "Анализируем бизнес-процессы",
            "Повторно выявляем функции по сформированному регламенту и готовим таблицу ИИ-агентов.",
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                suggestions = self._api.reanalyze_revision_document(draft_id)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._supplement_in_progress = False
            self._agents_table_ready.emit(suggestions)

        Thread(target=run, daemon=True).start()

    def _show_revision_result(self, result: object) -> None:
        if not isinstance(result, RegulationRevisionResult):
            return
        self._current_revision = result
        self._page_revision.set_result(result)
        self._pages.setCurrentIndex(self._page_index["revision"])

    def _on_revision_download(self, kind: str) -> None:
        if self._current_revision is None:
            return
        if kind == "protocol":
            url = self._current_revision.protocol_url
            default_name = "change_protocol.txt"
        elif kind == "pdf":
            url = self._current_revision.pdf_download_url
            default_name = "ai-ready-regulation.pdf"
        else:
            url = self._current_revision.download_url
            default_name = "ai-ready-regulation.docx"
        if not url:
            return
        target, _filter = QFileDialog.getSaveFileName(self, "Сохранить файл", default_name)
        if not target:
            return

        def run() -> None:
            try:
                data = self._api.fetch_bytes(url)
                with open(target, "wb") as fh:
                    fh.write(data)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)

        Thread(target=run, daemon=True).start()

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
        if key == "agents":
            self._page_agents.show_agents()
            self._load_agent_drafts()

    def _on_open_saved_workflow(self, record: object) -> None:
        from app.api_client import WorkflowRecord as WorkflowRecordType

        if not isinstance(record, WorkflowRecordType):
            return
        self._page_workflows.load_record(record)
        self._pages.setCurrentIndex(self._page_index["workflows"])

    def _load_agent_drafts(self) -> None:
        def run() -> None:
            try:
                drafts = self._api.list_agent_drafts()
                workflows = self._api.list_workflows()
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._drafts_ready.emit((drafts, workflows))

        Thread(target=run, daemon=True).start()

    def _show_drafts_result(self, result: object) -> None:
        if isinstance(result, tuple) and len(result) >= 2:
            drafts = [item for item in result[0] if isinstance(item, AgentDraft)] if isinstance(result[0], list) else []
            workflows = (
                [item for item in result[1] if isinstance(item, WorkflowListItem)]
                if isinstance(result[1], list)
                else []
            )
            self._page_agents.set_agents(workflows)
            self._page_agents.set_drafts(drafts)
            return
        if isinstance(result, list):
            self._page_agents.set_drafts([item for item in result if isinstance(item, AgentDraft)])

    def _show_agents_table_result(self, result: object) -> None:
        if isinstance(result, list) and all(isinstance(item, AgentSuggestion) for item in result):
            self._page_agents.show_drafts()
            self._pages.setCurrentIndex(self._page_index["agents"])
            self._load_agent_drafts()
            return
        elif isinstance(result, list):
            self._page_agents.set_drafts([item for item in result if isinstance(item, AgentDraft)])
        self._pages.setCurrentIndex(self._page_index["agents"])

    def _show_implementation_agents(self, result: object) -> None:
        workflows: list[WorkflowListItem] = []
        raw_suggestions = result
        self._implementation_draft_id = ""
        if isinstance(result, tuple) and len(result) >= 2:
            raw_suggestions = result[0]
            workflows = [item for item in result[1] if isinstance(item, WorkflowListItem)] if isinstance(result[1], list) else []
            if len(result) >= 3:
                self._implementation_draft_id = str(result[2] or "")
        suggestions = (
            [item for item in raw_suggestions if isinstance(item, AgentSuggestion)]
            if isinstance(raw_suggestions, list)
            else []
        )
        self.sidebar.set_active_key("create", animate=False)
        self._page_implementation_agents.set_suggestions(suggestions, created_agents=workflows)
        self._pages.setCurrentIndex(self._page_index["implementation_agents"])

    def _on_create_agent_from_suggestion(self, agent_id: str) -> None:
        suggestion = self._page_agents.find_suggestion(agent_id)
        if suggestion is None:
            QMessageBox.warning(self, "Агент", "Не удалось найти бизнес-процесс для создания агента.")
            return
        self._current_passport_suggestion = suggestion
        self._current_passport_draft_id = ""
        self._current_passport_agent_id = ""
        self._pages.setCurrentIndex(self._page_index["passport"])
        self._page_passport.start(suggestion)

    def _on_create_agent_from_draft_suggestion(self, draft_id: str, agent_id: str) -> None:
        suggestion = self._page_agents.find_suggestion(agent_id, draft_id=draft_id)
        if suggestion is None:
            QMessageBox.warning(self, "Агент", "Не удалось найти бизнес-процесс для создания агента.")
            return
        self._current_passport_suggestion = suggestion
        self._current_passport_draft_id = draft_id
        self._current_passport_agent_id = agent_id
        self._pages.setCurrentIndex(self._page_index["passport"])
        self._page_passport.start(suggestion)

    def _on_create_agent_from_inline_suggestion(self, suggestion: object) -> None:
        if not isinstance(suggestion, AgentSuggestion):
            QMessageBox.warning(self, "Агент", "Не удалось найти бизнес-процесс для создания агента.")
            return
        self._current_passport_suggestion = suggestion
        self._current_passport_draft_id = self._implementation_draft_id
        self._current_passport_agent_id = suggestion.agent_id if self._implementation_draft_id else ""
        self._pages.setCurrentIndex(self._page_index["passport"])
        self._page_passport.start(suggestion)

    def _on_passport_draft_requested(self, suggestion: object) -> None:
        if not isinstance(suggestion, AgentSuggestion):
            return

        def run() -> None:
            try:
                session = self._api.draft_passport_from_suggestion(suggestion)
            except ApiError as exc:
                self._passport_failed.emit(exc.message)
                return
            self._passport_ready.emit(session)

        Thread(target=run, daemon=True).start()

    def _on_passport_answer_requested(self, answers: object) -> None:
        session = self._page_passport.current_session()
        if session is None or not isinstance(answers, dict):
            return
        if isinstance(answers.get("answers"), dict) or "files" in answers:
            raw_answers = answers.get("answers") if isinstance(answers.get("answers"), dict) else {
                key: value for key, value in answers.items() if key != "files"
            }
            files = [str(path) for path in (answers.get("files") or []) if str(path).strip()]
        else:
            raw_answers = answers
            files = []
        merged = {str(key): str(value) for key, value in dict(raw_answers or {}).items()}

        def run() -> None:
            answers_payload = dict(merged)
            attachment_block = format_attachments_block(files)
            if attachment_block:
                if answers_payload:
                    answers_payload = {
                        key: (value + attachment_block).strip()
                        for key, value in answers_payload.items()
                    }
                else:
                    answers_payload = {"answer": attachment_block.strip()}
            try:
                updated = self._api.complete_passport(
                    session.passport,
                    answers=answers_payload,
                    bp_name=session.bp_name,
                    excerpt=session.excerpt,
                    functions=session.functions,
                )
            except ApiError as exc:
                self._passport_failed.emit(exc.message)
                return
            self._passport_ready.emit(updated)

        Thread(target=run, daemon=True).start()

    def _show_passport_result(self, result: object) -> None:
        if isinstance(result, PassportSession):
            self._page_passport.apply_session(result)
            self._pages.setCurrentIndex(self._page_index["passport"])

    def _show_passport_error(self, message: str) -> None:
        self._page_passport.show_error(message)
        self._pages.setCurrentIndex(self._page_index["passport"])

    def _on_passport_finished(self, session: object) -> None:
        if not isinstance(session, PassportSession):
            return
        self._page_workflows.start_from_passport(session, auto_plan=True)
        self._pages.setCurrentIndex(self._page_index["workflows"])

    def _on_launch_workflow_agent(self, record: object) -> None:
        if not isinstance(record, WorkflowRecord):
            return
        self.sidebar.set_active_key("agents", animate=False)
        self._page_agent_run.start(record)
        self._pages.setCurrentIndex(self._page_index["agent_run"])

    def _on_workflow_record_saved(self, record: object) -> None:
        if str(getattr(record, "phase", "")) != "done":
            return
        # Keep passport suggestion in «Черновики». Removing it on publish made the
        # card disappear while the published agent lives under «Мои агенты».
        # Remember source ids on the workflow so a later delete can stay consistent.
        draft_id = self._current_passport_draft_id
        agent_id = self._current_passport_agent_id
        workflow_id = str(getattr(record, "id", "") or "")
        self._current_passport_draft_id = ""
        self._current_passport_agent_id = ""

        def run() -> None:
            try:
                if workflow_id and draft_id and agent_id:
                    local = dict(getattr(record, "local_run", None) or {})
                    local["source_draft_id"] = draft_id
                    local["source_agent_id"] = agent_id
                    self._api.update_workflow_local_run(workflow_id, local)
                drafts = self._api.list_agent_drafts()
                workflows = self._api.list_workflows()
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._drafts_ready.emit((drafts, workflows))

        Thread(target=run, daemon=True).start()

    def _on_continue_agent_draft(self, draft_id: str) -> None:
        self._page_loading.set_message(
            "Открываем черновик ИИ-агента",
            "Загружаем состояние готовности и текущий вопрос.",
        )
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                draft = self._api.ensure_draft_readiness(draft_id)
                if draft.status == "ready" and not draft.agent_suggestions:
                    draft = self._api.update_agent_draft_status(draft.draft_id, "ready")
                if draft.status == "ready" and draft.agent_suggestions:
                    workflows = self._api.list_workflows()
                    self._implementation_agents_ready.emit((draft.agent_suggestions, workflows, draft.draft_id))
                    return
                chat = self._first_chat_for_draft(draft)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._draft_ready.emit((draft, chat))

        Thread(target=run, daemon=True).start()

    def _on_delete_agent_draft(self, draft_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Удалить черновик",
            "Удалить этот черновик ИИ-агента? Это действие нельзя отменить.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def run() -> None:
            try:
                self._api.delete_agent_draft(draft_id)
                drafts = self._api.list_agent_drafts()
                workflows = self._api.list_workflows()
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._drafts_ready.emit((drafts, workflows))

        Thread(target=run, daemon=True).start()

    def _on_delete_agent_suggestion(self, draft_id: str, agent_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Удалить черновик",
            "Удалить этот черновик ИИ-агента? Это действие нельзя отменить.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def run() -> None:
            try:
                self._api.delete_agent_draft_suggestion(draft_id, agent_id)
                drafts = self._api.list_agent_drafts()
                workflows = self._api.list_workflows()
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._drafts_ready.emit((drafts, workflows))

        Thread(target=run, daemon=True).start()

    def _on_delete_published_agent(self, workflow_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Удалить ИИ-агента",
            "Удалить этого опубликованного ИИ-агента? Это действие нельзя отменить.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def run() -> None:
            try:
                self._api.delete_workflow(workflow_id)
                drafts = self._api.list_agent_drafts()
                workflows = self._api.list_workflows()
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._drafts_ready.emit((drafts, workflows))

        Thread(target=run, daemon=True).start()

    def _on_run_published_agent(self, workflow_id: str) -> None:
        def run() -> None:
            try:
                record = self._api.get_workflow(workflow_id)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._published_agent_ready.emit(record)

        Thread(target=run, daemon=True).start()


def _suggestions_from_role_match(role_match: RoleMatchResult | None) -> list[AgentSuggestion]:
    if role_match is None:
        return []
    functions = role_match.functions or [
        match.function
        for match in role_match.matches
        if match.function is not None and match.status != "rejected"
    ]
    suggestions: list[AgentSuggestion] = []
    seen: set[str] = set()
    for index, function in enumerate(functions, start=1):
        if function is None:
            continue
        if not function.is_function and not (function.action or function.object):
            continue
        key = function.duplicate_group or function.function_id or f"{function.action}:{function.object}"
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            AgentSuggestion(
                agent_id=f"agent-suggestion-{index:03d}",
                title=_suggestion_title(function, index),
                description=_suggestion_description(function),
                regulation_id=role_match.regulation_id,
                role_match_run_id=role_match.run_id,
                function_id=function.function_id,
                source_block_id=function.target_block_id,
            )
        )
    return suggestions


def _suggestion_title(function, index: int) -> str:
    explicit = (getattr(function, "title", "") or "").strip()
    if explicit:
        cleaned = explicit.split("→", 1)[0].strip()
        if cleaned:
            return f"ИИ-агент: {cleaned}"[:180]
    action = (function.action or "").strip()
    obj = (function.object or "").strip()
    if action and obj:
        return f"ИИ-агент: {action} {obj}"[:180]
    if action:
        return f"ИИ-агент: {action}"[:180]
    return f"ИИ-агент для бизнес-процесса {index}"


def _suggestion_description(function) -> str:
    parts: list[str] = []
    actor = getattr(function, "actor", None)
    if actor is not None and actor.canonical_position:
        parts.append(f"Роль: {actor.canonical_position}")
    if function.conditions:
        parts.append("Условия: " + "; ".join(function.conditions[:2]))
    if function.recipient:
        parts.append(f"Получатель/участник: {function.recipient}")
    if function.explanation:
        parts.append(function.explanation)
    return "\n".join(part for part in parts if part).strip()
