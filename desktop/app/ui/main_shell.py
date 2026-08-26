from __future__ import annotations

from pathlib import Path
from threading import Thread

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
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
    ScheduleDraft,
    ScheduleTriggerSpec,
    WorkflowBoard,
    WorkflowListItem,
    WorkflowRecord,
    _parse_schedule_draft,
    _parse_workflow_board,
    without_deleted_workflows,
)
from app.ui.pages.agent_passport_page import AgentPassportPage
from app.ui.pages.agent_kpi_preview_page import AgentKpiPreviewPage
from app.ui.pages.agent_schedule_page import AgentSchedulePage
from app.ui.pages.agent_implementation_page import AgentImplementationPage
from app.ui.pages.agent_group_runs_page import AgentGroupRunsPage
from app.ui.pages.agent_history_page import AgentHistoryPage
from app.ui.pages.agent_run_page import AgentRunPage
from app.ui.pages.create_agent_page import CreateAgentPage
from app.ui.pages.kpi_page import KpiPage
from app.ui.pages.my_agents_page import MyAgentsPage
from app.ui.pages.my_dashboard_page import MyDashboardPage
from app.ui.pages.regulation_review_page import RegulationReviewPage
from app.ui.pages.regulation_creation_page import RegulationCreationPage
from app.ui.pages.readiness_page import ReadinessPage
from app.ui.pages.revision_result_page import RevisionResultPage
from app.ui.pages.role_match_page import RoleMatchPage
from app.ui.pages.saved_workflows_page import SavedWorkflowsPage
from app.ui.pages.notifications_page import NotificationsPage
from app.ui.pages.orchestrator_page import OrchestratorPage
from app.chat.page import ChatPage
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
from app.ui.widgets.detached_tab import DetachedTabWindow
from app.ui.widgets.dock_layout import (
    FLOAT,
    detach_key,
    first_docked_key,
    load_float_geom,
    load_layout,
    move_key,
    save_float_geom,
    save_layout,
)
from app.ui.widgets.dock_overlay import DockDropOverlay
from app.ui.widgets.dock_rail import DockRail
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


class PlatformFilesPage(QWidget):
    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(14)
        title = QLabel("Файлы")
        title.setFont(app_font(28, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        subtitle = QLabel("Все документы, которые приложены к агентам или созданы ими.")
        subtitle.setFont(app_font(13))
        subtitle.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Поиск по файлам")
        self._search.setFixedHeight(38)
        self._search.setStyleSheet(
            "QLineEdit { background: #FFFFFF; border: 1px solid rgba(16,24,23,0.10); "
            "border-radius: 12px; padding: 8px 12px; }"
        )
        self._search.textChanged.connect(lambda _text: self._render())
        refresh = QPushButton("Обновить")
        refresh.setFixedHeight(38)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.setStyleSheet(
            "QPushButton { background: #08745F; color: #FFFFFF; border: none; "
            "border-radius: 12px; padding: 8px 14px; }"
        )
        refresh.clicked.connect(self.refresh)
        row.addWidget(self._search, 1)
        row.addWidget(refresh, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._content = QWidget()
        self._content_lay = QVBoxLayout(self._content)
        self._content_lay.setContentsMargins(0, 0, 0, 0)
        self._content_lay.setSpacing(10)
        self._scroll.setWidget(self._content)
        self._items: list[tuple[str, str, str]] = []
        self._message = ""
        root.addWidget(title)
        root.addWidget(subtitle)
        root.addLayout(row)
        root.addWidget(self._scroll, 1)
        self._render()

    def refresh(self) -> None:
        self._message = ""
        items: list[tuple[str, str, str]] = []
        try:
            for workflow in self._api.list_workflows():
                files = self._api.list_workflow_files(workflow.id)
                for item in list(files.user_files) + list(files.agent_files):
                    items.append((workflow.title, item.filename, item.summary or item.text_preview))
        except ApiError:
            self._message = "Не удалось загрузить базу файлов. Проверьте соединение и попробуйте снова."
        self._items = items
        self._render()

    def _render(self) -> None:
        while self._content_lay.count():
            item = self._content_lay.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        query = self._search.text().strip().casefold()
        rows = [item for item in self._items if not query or query in item[1].casefold()]
        if self._message:
            self._content_lay.addWidget(self._empty(self._message))
        elif not rows:
            self._content_lay.addWidget(self._empty("Файлов пока нет. Они появятся после загрузки материалов в агентах."))
        else:
            for workflow, filename, summary in rows:
                self._content_lay.addWidget(self._card(workflow, filename, summary))
        self._content_lay.addStretch(1)

    def _empty(self, text: str) -> QWidget:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setFont(app_font(14))
        label.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent; padding: 40px;")
        return label

    def _card(self, workflow: str, filename: str, summary: str) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            "QFrame { background: #FFFFFF; border: 1px solid rgba(16,24,23,0.08); border-radius: 14px; }"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 12, 14, 12)
        name = QLabel(filename or "file")
        name.setFont(app_font(14, QFont.Weight.DemiBold))
        name.setStyleSheet(f"color: {MAIN_TEXT.name()}; background: transparent;")
        meta = QLabel(workflow or "Агент")
        meta.setFont(app_font(11))
        meta.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        info = QLabel((summary or "").strip()[:220])
        info.setWordWrap(True)
        info.setFont(app_font(12))
        info.setStyleSheet(f"color: {COLOR_CONTENT_MUTED.name()}; background: transparent;")
        lay.addWidget(name)
        lay.addWidget(meta)
        if info.text():
            lay.addWidget(info)
        return card


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
    _board_reload = Signal()
    _agents_table_ready = Signal(object)
    _implementation_agents_ready = Signal(object)
    _passport_ready = Signal(object)
    _passport_failed = Signal(str)
    _published_agent_ready = Signal(object)
    _workflow_page_ready = Signal(object)
    _chat_ready = Signal(object)
    _creation_session_ready = Signal(object)
    _creation_stream_event = Signal(str, str)
    _agent_history_ready = Signal(object)
    _schedule_draft_ready = Signal(object)
    _schedule_save_ready = Signal(object)
    _kpi_preview_ready = Signal(object)
    _schedule_failed = Signal(str)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._user: UserProfile | None = None
        self._avatar_pixmap = QPixmap()
        self._deleted_workflow_ids: set[str] = set()
        self._pending_start_demo = False

        self.sidebar = GlassSidebar(
            self,
            search_users=self._api.search_users,
            fetch_avatar=self._fetch_peer_avatar,
        )
        self.sidebar.page_changed.connect(self._on_page_changed)
        self.sidebar.collapse_toggled.connect(self._on_sidebar_collapse)
        self.sidebar.dialog_selected.connect(self._on_sidebar_dialog)
        self.sidebar.fio_search_chosen.connect(self._on_sidebar_fio)

        self._pages = QStackedWidget()
        self._page_create = CreateAgentPage()
        self._page_agents = MyAgentsPage()
        self._page_implementation_agents = AgentImplementationPage()
        self._page_workflows = WorkflowPage(self._api)
        self._page_agent_run = AgentRunPage(self._api)
        self._page_saved_workflows = SavedWorkflowsPage(self._api)
        self._page_files = PlatformFilesPage(self._api)
        self._page_kpi = KpiPage(self._api)
        self._page_dashboard = MyDashboardPage(self._api)
        self._page_settings = SettingsPage(self._api)
        self._page_review = RegulationReviewPage()
        self._page_role_match = RoleMatchPage()
        self._page_readiness = ReadinessPage()
        self._page_revision = RevisionResultPage(self._api)
        self._page_creation_chat = RegulationCreationPage()
        self._page_passport = AgentPassportPage()
        self._page_schedule = AgentSchedulePage()
        self._page_kpi_preview = AgentKpiPreviewPage(self._api)
        self._page_loading = LoadingPage()
        self._page_notifications = NotificationsPage()
        self._page_history = AgentHistoryPage(self._api)
        self._page_group_runs = AgentGroupRunsPage()
        self._page_chat = ChatPage(self._api)
        self._page_chat.open_agent_requested.connect(self._on_agent_history_requested)
        self._page_orchestrator = OrchestratorPage()
        self._page_chat.threads_changed.connect(self._sync_sidebar_dialogs)
        self._page_orchestrator.run_requested.connect(self.navigate_to_agent_run)
        self._pages.addWidget(self._page_create)
        self._pages.addWidget(self._page_agents)
        self._pages.addWidget(self._page_implementation_agents)
        self._pages.addWidget(self._page_workflows)
        self._pages.addWidget(self._page_agent_run)
        self._pages.addWidget(self._page_saved_workflows)
        self._pages.addWidget(self._page_files)
        self._pages.addWidget(self._page_kpi)
        self._pages.addWidget(self._page_dashboard)
        self._pages.addWidget(self._page_settings)
        self._pages.addWidget(self._page_review)
        self._pages.addWidget(self._page_role_match)
        self._pages.addWidget(self._page_readiness)
        self._pages.addWidget(self._page_revision)
        self._pages.addWidget(self._page_creation_chat)
        self._pages.addWidget(self._page_passport)
        self._pages.addWidget(self._page_schedule)
        self._pages.addWidget(self._page_loading)
        self._pages.addWidget(self._page_kpi_preview)
        self._pages.addWidget(self._page_notifications)
        self._pages.addWidget(self._page_history)
        self._pages.addWidget(self._page_group_runs)
        self._pages.addWidget(self._page_chat)
        self._pages.addWidget(self._page_orchestrator)
        self._page_index = {
            "create": 0,
            "agents": 1,
            "implementation_agents": 2,
            "workflows": 3,
            "agent_run": 4,
            "saved_workflows": 5,
            "files": 6,
            "kpi": 7,
            "dashboard": 8,
            "settings": 9,
            "review": 10,
            "role_match": 11,
            "readiness": 12,
            "revision": 13,
            "creation_chat": 14,
            "passport": 15,
            "schedule": 16,
            "loading": 17,
            "kpi_preview": 18,
            "notifications": 19,
            "agent_history": 20,
            "agent_group_runs": 21,
            "chat": 22,
            "orchestrator": 23,
        }
        self._nav_pages = {
            "create": self._page_create,
            "agents": self._page_agents,
            "files": self._page_files,
            "kpi": self._page_kpi,
            "dashboard": self._page_dashboard,
            "orchestrator": self._page_orchestrator,
            "chat": self._page_chat,
        }
        self._float_windows: dict[str, DetachedTabWindow] = {}
        self._dragging_key = ""
        self._drag_consumed = False
        self._page_workflows.saved.connect(lambda _id: self._page_saved_workflows.refresh())
        self._page_workflows.saved_record.connect(self._on_workflow_record_saved)
        self._page_workflows.launch_requested.connect(self._on_launch_workflow_agent)
        self._page_workflows.schedule_requested.connect(self._on_schedule_requested)
        self._page_schedule.back_requested.connect(self._on_schedule_back)
        self._page_schedule.save_requested.connect(self._on_schedule_save)
        self._page_kpi_preview.back_requested.connect(self._on_kpi_back)
        self._page_kpi_preview.confirm_requested.connect(self._on_kpi_confirm)
        self._page_saved_workflows.open_requested.connect(self._on_open_saved_workflow)
        self._page_implementation_agents.create_requested.connect(self._on_create_agent_from_inline_suggestion)
        self._page_settings.profile_updated.connect(self._on_profile_updated)
        self._page_agents.continue_requested.connect(self._on_continue_agent_draft)
        self._page_agents.create_requested.connect(self._on_create_agent_from_suggestion)
        self._page_agents.create_suggestion_requested.connect(self._on_create_agent_from_draft_suggestion)
        self._page_agents.delete_requested.connect(self._on_delete_agent_draft)
        self._page_agents.delete_suggestion_requested.connect(self._on_delete_agent_suggestion)
        self._page_agents.delete_agent_requested.connect(self._on_delete_published_agent)
        self._page_agents.stop_auto_run_requested.connect(self._on_stop_published_agent)
        self._page_agents.resume_auto_run_requested.connect(self._on_resume_published_agent)
        self._page_agents.run_agent_requested.connect(self._on_run_published_agent)
        self._page_agents.history_requested.connect(self._on_agent_history_requested)
        self._page_agents.open_agent_requested.connect(self._on_agent_history_requested)
        self._page_agents.open_run_requested.connect(self._on_calendar_run_requested)
        self._page_agents.group_runs_requested.connect(self._on_group_runs_requested)
        self._page_agents.create_agent_requested.connect(self._on_create_agent_from_board)
        self._page_agents.schedule_requested.connect(self._on_board_schedule_requested)
        self._page_agents.schedule_run_requested.connect(self._on_board_schedule_run)
        self._page_agents.board_range_changed.connect(self._load_agent_drafts)
        self._page_history.back_requested.connect(lambda: self._show_page("agents"))
        self._page_group_runs.back_requested.connect(lambda: self._show_page("agents"))
        self._page_group_runs.open_requested.connect(self._on_calendar_run_requested)
        self._page_history.failed.connect(self._readiness_failed.emit)
        self._page_passport.back_requested.connect(lambda: self._show_page("agents"))
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
        self._board_reload.connect(self._load_agent_drafts)
        self._board_live_timer = QTimer(self)
        self._board_live_timer.setSingleShot(True)
        self._board_live_timer.setInterval(250)
        self._board_live_timer.timeout.connect(self._flush_live_board)
        self._pending_live_board: dict | None = None
        self._agents_table_ready.connect(self._show_agents_table_result)
        self._implementation_agents_ready.connect(self._show_implementation_agents)
        self._passport_ready.connect(self._show_passport_result)
        self._passport_failed.connect(self._show_passport_error)
        self._published_agent_ready.connect(self._on_launch_workflow_agent)
        self._workflow_page_ready.connect(self._on_open_saved_workflow)
        self._chat_ready.connect(self._show_chat_result)
        self._creation_session_ready.connect(self._show_creation_session)
        self._creation_stream_event.connect(self._page_creation_chat.append_stream_event)
        self._agent_history_ready.connect(self._show_agent_history)
        self._schedule_draft_ready.connect(self._show_schedule_page)
        self._schedule_save_ready.connect(self._show_schedule_saved)
        self._kpi_preview_ready.connect(self._show_kpi_preview)
        self._schedule_failed.connect(self._show_schedule_error)
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
        self._current_passport_suggestion = None
        self._schedule_from_agents = False
        self._auto_finalize_running = False
        self._supplement_in_progress = False

        self.user_menu = UserMenuHeader(self)
        self.user_menu.logout_requested.connect(self.logout_requested.emit)
        self.user_menu.settings_requested.connect(self._open_settings)
        self.user_menu.notifications_requested.connect(self._open_notifications)
        self._page_notifications.mark_all_requested.connect(self._mark_all_notifications_read)
        self._page_notifications.clear_requested.connect(self._clear_notifications)
        self._page_notifications.item_opened.connect(self._on_notification_opened)
        self._page_notifications.open_workflow_requested.connect(self._on_launch_workflow_from_inbox)
        self._notify_timer = QTimer(self)
        self._notify_timer.setInterval(20000)
        self._notify_timer.timeout.connect(self.refresh_notification_badge)

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

        self._rail_top = DockRail("top", self)
        self._rail_right = DockRail("right", self)
        self._rail_bottom = DockRail("bottom", self)
        center = QWidget(self)
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        center_layout.addWidget(self._rail_top, 0)
        center_layout.addWidget(self._content, 1)
        center_layout.addWidget(self._rail_bottom, 0)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.sidebar, 0)
        root.addWidget(center, 1)
        root.addWidget(self._rail_right, 0)

        self._dock_overlay = DockDropOverlay(self)
        self._dock_layout = load_layout()
        for rail in (self._rail_top, self._rail_right, self._rail_bottom):
            rail.page_changed.connect(self._on_page_changed)
            rail.drag_started.connect(self._on_nav_drag)
            rail.drag_finished.connect(self._on_nav_drag_end)
        self.sidebar.drag_started.connect(self._on_nav_drag)
        self.sidebar.drag_finished.connect(self._on_nav_drag_end)
        self._dock_overlay.dropped.connect(self._on_nav_docked)

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

        self._apply_dock_layout(save=False)
        self.sidebar.set_active_key("create", animate=False)
        QTimer.singleShot(0, self._restore_floated_tabs)
        QTimer.singleShot(0, self._position_overlays)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._dock_overlay.setGeometry(self.rect())
        self._position_overlays()

    def _on_nav_drag(self, key: str) -> None:
        self._dragging_key = key
        self._drag_consumed = False
        self._dock_overlay.setGeometry(self.rect())
        self._dock_overlay.show()
        self._dock_overlay.raise_()

    def _on_nav_drag_end(self) -> None:
        self._dock_overlay.hide()
        key = self._dragging_key
        consumed = self._drag_consumed
        self._dragging_key = ""
        self._drag_consumed = False
        if consumed or not key:
            return
        pos = QCursor.pos()
        host = self.window()
        if host is not None and not host.frameGeometry().contains(pos):
            self._detach_tab(key, pos)

    def _on_nav_docked(self, side: str, key: str) -> None:
        self._drag_consumed = True
        if side == FLOAT:
            self._detach_tab(key)
            return
        if key in self._float_windows:
            self._redock_tab(key, side)
            return
        self._dock_layout = move_key(self._dock_layout, key, side)
        self._apply_dock_layout()
        self._sync_nav_active(self.sidebar.active_key())

    def _apply_dock_layout(self, *, save: bool = True) -> None:
        self.sidebar.set_keys(self._dock_layout.get("left") or [])
        left_has = bool(self._dock_layout.get("left"))
        self.sidebar.setVisible(left_has)
        if hasattr(self, "_collapse_btn"):
            self._collapse_btn.setVisible(left_has)
        self._rail_top.set_keys(self._dock_layout.get("top") or [])
        self._rail_right.set_keys(self._dock_layout.get("right") or [])
        self._rail_bottom.set_keys(self._dock_layout.get("bottom") or [])
        if save:
            save_layout(self._dock_layout)
        QTimer.singleShot(0, self._position_overlays)

    def _sync_nav_active(self, key: str) -> None:
        self.sidebar.mark_active(key)
        self._rail_top.mark_active(key)
        self._rail_right.mark_active(key)
        self._rail_bottom.mark_active(key)

    def _position_overlays(self) -> None:
        self._position_collapse_btn()
        self._position_user_menu()

    def _position_collapse_btn(self) -> None:
        btn = self._collapse_btn
        if not self.sidebar.isVisible():
            btn.hide()
            return
        btn.show()
        origin = self.sidebar.mapTo(self, self.sidebar.rect().topLeft())
        if self.sidebar.is_collapsed():
            x = origin.x() + (self.sidebar.width() - btn.width()) // 2
        else:
            x = origin.x() + self.sidebar.width() - btn.width() - 12
        y = origin.y() + self.sidebar.height() - btn.height() - 22
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

    def set_user(self, user: UserProfile, *, reset_home: bool = True) -> None:
        self._apply_user(user)
        if reset_home:
            from app.chat.test_user import is_ilchenko_user

            start_key = "orchestrator" if is_ilchenko_user(user.id, user.fio) else "create"
            self.sidebar.set_active_key(start_key, animate=False)
            idx = self._page_index.get(start_key, 0)
            self._pages.setCurrentIndex(idx)
        QTimer.singleShot(0, self._refresh_profile)

    def _apply_user(self, user: UserProfile) -> None:
        self._user = user
        self._api._user_id = user.id
        self.user_menu.set_user(
            fio=user.fio,
            position=user.position,
            activity_status=user.activity_status,
        )
        self._page_chat.set_user(user)
        self._page_orchestrator.set_user(user.id, user.fio)
        if self._is_local_test_user():
            self._page_orchestrator.set_bound_agents(self._local_session_board().agents)
        QTimer.singleShot(0, self._ensure_backend_token)
        self._sync_sidebar_dialogs()
        self._load_avatar(user)
        pixmap = None if self._avatar_pixmap.isNull() else self._avatar_pixmap
        self._page_settings.set_user(user, pixmap)
        if not self._notify_timer.isActive():
            self._notify_timer.start()
        QTimer.singleShot(0, self.refresh_notification_badge)

    def _fetch_peer_avatar(self, peer_id: str) -> QPixmap:
        from app.chat.avatars import load_peer_avatar

        return load_peer_avatar(self._api, peer_id)

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

    def apply_chat_event(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        from app.chat.events import dispatch

        dispatch(payload, self._page_chat.apply_event)
        if str(payload.get("type") or "") == "presence" and self._user is not None:
            if str(payload.get("user_id") or "") == self._user.id:
                from dataclasses import replace

                status = str(payload.get("activity_status") or self._user.activity_status)
                self._apply_user(replace(self._user, activity_status=status))

    def refresh_notification_badge(self) -> None:
        try:
            count = self._api.unread_notification_count()
        except ApiError:
            return
        self.user_menu.set_unread_count(count)
        if self._pages.currentIndex() == self._page_index.get("notifications"):
            self._reload_notifications_page()

    def _open_notifications(self) -> None:
        self._reload_notifications_page()
        self._pages.setCurrentIndex(self._page_index["notifications"])

    def _reload_notifications_page(self) -> None:
        try:
            items, unread = self._api.list_inbox()
        except ApiError as exc:
            QMessageBox.information(self, "Уведомления", exc.message)
            return
        self._page_notifications.set_items(items)
        self.user_menu.set_unread_count(unread)

    def _mark_all_notifications_read(self) -> None:
        try:
            self._api.mark_all_notifications_read()
        except ApiError as exc:
            QMessageBox.information(self, "Уведомления", exc.message)
            return
        self._reload_notifications_page()

    def _clear_notifications(self) -> None:
        answer = QMessageBox.question(
            self,
            "Очистить уведомления",
            "Удалить все уведомления? Это действие нельзя отменить.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self._api.clear_notifications()
        except ApiError as exc:
            QMessageBox.information(self, "Уведомления", exc.message)
            return
        self._reload_notifications_page()
        self.refresh_notification_badge()

    def _on_notification_opened(self, notification_id: str) -> None:
        try:
            self._api.mark_notification_read(notification_id)
        except ApiError:
            return
        self.refresh_notification_badge()

    def _on_launch_workflow_from_inbox(self, workflow_id: str, run_id: str = "") -> None:
        wid = (workflow_id or "").strip()
        if not wid:
            return
        try:
            self._api.get_workflow(wid)
        except ApiError as exc:
            QMessageBox.information(
                self,
                "Уведомления",
                "Этот агент удалён. Перейти к нему больше нельзя."
                if exc.status_code == 404
                else exc.message,
            )
            self._reload_notifications_page()
            return
        from app.tools.hitl import notification_opens_live

        if notification_opens_live(wid):
            self.show_live_agent(wid)
            return
        self.navigate_to_agent_history(wid, run_id)

    def _open_settings(self) -> None:
        if self._user is not None:
            pixmap = None if self._avatar_pixmap.isNull() else self._avatar_pixmap
            self._page_settings.set_user(self._user, pixmap)
        self._pages.setCurrentIndex(self._page_index["settings"])

    def _on_profile_updated(self, user: object) -> None:
        if isinstance(user, UserProfile):
            self._apply_user(user)

    def _on_create_regulation(self) -> None:
        if not self._ensure_backend_token():
            self._show_regulation_error(
                "Нет сессии на сервере. Для создания регламента нужен вход, который выдаёт токен."
            )
            return
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
        use_local = self._is_local_test_user() and not self._ensure_backend_token()

        def run() -> None:
            try:
                if use_local:
                    from app.local_auth import parse_local_regulation

                    result = parse_local_regulation(path)
                else:
                    result = self._api.upload_regulation(path)
            except ApiError as exc:
                if not self._is_local_test_user():
                    self._regulation_failed.emit(exc.message)
                    return
                from app.local_auth import parse_local_regulation

                try:
                    result = parse_local_regulation(path)
                except Exception:
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
        if self._pages.currentIndex() == self._page_index["loading"]:
            self._pages.setCurrentIndex(self._page_index["create"])
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
                if self._is_local_test_user() and not self._api.token:
                    from app.local_auth import local_role_match

                    result = local_role_match(self._current_regulation, position, department)
                else:
                    result = self._api.extract_regulation_functions(
                        self._current_regulation.regulation_id,
                        position=position,
                        department=department,
                    )
            except ApiError as exc:
                if self._is_local_test_user():
                    from app.local_auth import local_role_match

                    result = local_role_match(self._current_regulation, position, department)
                    self._role_match_ready.emit(result)
                    return
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

    def _is_local_test_user(self) -> bool:
        from app.chat.test_user import is_local_test_user

        user = self._user
        if user is None:
            return False
        return is_local_test_user(user.id, user.fio)

    def _is_local_test_session(self) -> bool:
        return not bool(getattr(self._api, "_token", None) or getattr(self._api, "token", None))

    def _token_accepted_by_server(self) -> bool:
        if not getattr(self._api, "token", None):
            return False
        try:
            self._api.me()
        except ApiError:
            self._api.set_token(None)
            return False
        return True

    def _ensure_backend_token(self) -> bool:
        if self._token_accepted_by_server():
            return True
        from app.chat.test_user import canonical_test_credentials
        from app.session_store import save_session

        user = self._user
        creds = canonical_test_credentials(
            user_id=user.id if user is not None else "",
            fio=user.fio if user is not None else "",
        )
        if creds is None:
            return False
        try:
            result = self._api.login(*creds)
        except ApiError:
            return False
        if not result.access_token or not self._token_accepted_by_server():
            self._api.set_token(None)
            return False
        save_session(access_token=result.access_token, fio=result.user.fio or (user.fio if user else ""))
        return True

    def _local_session_board(self) -> WorkflowBoard:
        from app.orchestrator.agents import local_board

        return without_deleted_workflows(local_board(), self._deleted_workflow_ids)

    def _merge_local_board(self, board: WorkflowBoard) -> WorkflowBoard:
        if not self._is_local_test_user():
            return board
        from dataclasses import replace

        local = self._local_session_board()
        seen = {agent.id for agent in board.agents}
        extra = [agent for agent in local.agents if agent.id not in seen]
        if not extra:
            return board
        return replace(
            board,
            agents=[*extra, *board.agents],
            stats=replace(board.stats, active_agents=board.stats.active_agents + len(extra)),
        )

    def _show_role_match_error(self, message: str) -> None:
        if self._is_local_test_session():
            return
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
        if self._is_local_test_session():
            return
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

    def _show_page(self, key: str) -> None:
        window = self._float_windows.get(key)
        if window is not None:
            window.show()
            window.raise_()
            window.activateWindow()
            self._sync_nav_active(key)
            return
        idx = self._page_index.get(key)
        if idx is None:
            return
        self._pages.setCurrentIndex(idx)
        self._sync_nav_active(key)

    def _restore_floated_tabs(self) -> None:
        for key in list(self._dock_layout.get(FLOAT) or []):
            self._detach_tab(key, restore=True)

    def _detach_tab(self, key: str, pos=None, *, restore: bool = False) -> None:
        if key not in self._nav_pages:
            return
        if key in self._float_windows:
            self._show_page(key)
            return
        page = self._nav_pages[key]
        idx = self._pages.indexOf(page)
        if idx < 0:
            return
        placeholder = QWidget()
        placeholder.setObjectName(f"float_placeholder_{key}")
        self._pages.insertWidget(idx, placeholder)
        self._pages.removeWidget(page)
        window = DetachedTabWindow(key, page, self)
        window.closed.connect(self._on_float_closed)
        window.moved_or_resized.connect(self._on_float_geom)
        window.drag_started.connect(self._on_nav_drag)
        window.drag_finished.connect(self._on_nav_drag_end)
        geom = load_float_geom(key)
        if geom is not None:
            window.setGeometry(*geom)
        elif pos is not None:
            window.move(max(0, pos.x() - 80), max(0, pos.y() - 20))
        self._float_windows[key] = window
        self._dock_layout = detach_key(self._dock_layout, key)
        self._apply_dock_layout()
        next_key = first_docked_key(self._dock_layout)
        if next_key and self.sidebar.active_key() == key:
            self.sidebar.mark_active(next_key)
            self._show_page(next_key)
        window.show()
        if not restore:
            window.raise_()
            window.activateWindow()

    def _redock_tab(self, key: str, side: str = "left") -> None:
        window = self._float_windows.pop(key, None)
        page = self._nav_pages.get(key)
        if page is None:
            return
        if window is not None:
            window.closed.disconnect(self._on_float_closed)
            window.release_page()
            window.hide()
            window.deleteLater()
        idx = self._page_index.get(key)
        if idx is None:
            return
        placeholder = self._pages.widget(idx)
        self._pages.insertWidget(idx, page)
        if placeholder is not None and placeholder is not page:
            self._pages.removeWidget(placeholder)
            placeholder.deleteLater()
        page.show()
        self._dock_layout = move_key(self._dock_layout, key, side)
        self._apply_dock_layout()
        self._show_page(key)

    def _on_float_closed(self, key: str) -> None:
        if key in self._float_windows:
            self._redock_tab(key, "left")

    def _on_float_geom(self, key: str, x: int, y: int, width: int, height: int) -> None:
        save_float_geom(key, x, y, width, height)

    def _on_page_changed(self, key: str) -> None:
        if self._review_fullscreen:
            self._page_review.set_fullscreen(False)
        if key not in self._page_index:
            return
        self._show_page(key)
        if key == "agents":
            self._page_agents.show_agents()
            self._load_agent_drafts()
        elif key == "dashboard":
            self._page_dashboard.refresh()
        elif key == "kpi":
            self._page_kpi.refresh()
        elif key == "files":
            self._page_files.refresh()
        elif key == "chat":
            self._page_chat.refresh()
        elif key == "orchestrator":
            self._page_orchestrator.refresh()
        self.sidebar.hide_search_suggestions()

    def _sync_sidebar_dialogs(self) -> None:
        self.sidebar.set_dialogs(self._page_chat.sidebar_dialogs())
        current = self._page_chat.current_thread_id()
        if self.sidebar.active_key() == "chat" and current:
            self.sidebar.highlight_dialog(current)

    def _on_sidebar_dialog(self, thread_id: str) -> None:
        self._pages.setCurrentIndex(self._page_index["chat"])
        self._page_chat.open_existing_dialog(thread_id)

    def _on_sidebar_fio(self, fio: str) -> None:
        self._pages.setCurrentIndex(self._page_index["chat"])
        self._page_chat.open_by_fio(fio)
        current = self._page_chat.current_thread_id()
        if current:
            self.sidebar.highlight_dialog(current)
        self._sync_sidebar_dialogs()

    def _on_open_saved_workflow(self, record: object) -> None:
        from app.api_client import WorkflowRecord as WorkflowRecordType

        if not isinstance(record, WorkflowRecordType):
            return
        start_demo = self._pending_start_demo
        self._pending_start_demo = False
        self._page_workflows.load_record(record, auto_demo=start_demo)
        self._pages.setCurrentIndex(self._page_index["workflows"])

    def _load_agent_drafts(self) -> None:
        if self._is_local_test_user() and self._is_local_test_session():
            self._drafts_ready.emit((self._local_session_board(), []))
            return
        window_from, window_to = self._page_agents.calendar_window()

        def run() -> None:
            try:
                board = self._api.get_workflow_board(window_from=window_from, window_to=window_to)
                drafts = self._api.list_agent_drafts()
            except ApiError as exc:
                if self._is_local_test_user():
                    self._drafts_ready.emit((self._local_session_board(), []))
                    return
                self._readiness_failed.emit(exc.message)
                return
            self._drafts_ready.emit((board, drafts))

        Thread(target=run, daemon=True).start()

    def apply_live_board(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._pending_live_board = payload
        self._board_live_timer.start()

    def _flush_live_board(self) -> None:
        payload = self._pending_live_board
        self._pending_live_board = None
        if not isinstance(payload, dict) or not isinstance(payload.get("stats"), dict):
            self._load_agent_drafts()
            return
        board = without_deleted_workflows(
            _parse_workflow_board(payload),
            self._deleted_workflow_ids,
        )
        self._page_agents.set_board(board)

    def _show_drafts_result(self, result: object) -> None:
        if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[0], WorkflowBoard):
            board = self._merge_local_board(
                without_deleted_workflows(result[0], self._deleted_workflow_ids)
            )
            drafts = [item for item in result[1] if isinstance(item, AgentDraft)] if isinstance(result[1], list) else []
            self._page_agents.set_board(board)
            self._page_agents.set_drafts(drafts)
            self._page_orchestrator.set_bound_agents(board.agents)
            self.refresh_notification_badge()
            return
        if isinstance(result, tuple) and len(result) >= 2:
            drafts = [item for item in result[0] if isinstance(item, AgentDraft)] if isinstance(result[0], list) else []
            workflows = (
                [item for item in result[1] if isinstance(item, WorkflowListItem)]
                if isinstance(result[1], list)
                else []
            )
            self._page_agents.set_agents(workflows)
            self._page_agents.set_drafts(drafts)
            self.refresh_notification_badge()
            self._load_agent_drafts()
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
                session = self._api.draft_passport_from_suggestion(
                    suggestion,
                    draft_id=self._current_passport_draft_id,
                    agent_id=self._current_passport_agent_id,
                )
            except ApiError as exc:
                self._passport_failed.emit(exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                self._passport_failed.emit(f"Не удалось собрать паспорт: {exc}")
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
        suggestion = self._current_passport_suggestion
        qa_history = self._page_passport.qa_history()

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
                    draft_id=self._current_passport_draft_id or session.draft_id,
                    agent_id=self._current_passport_agent_id,
                    function_id=getattr(suggestion, "function_id", "") or "",
                    regulation_id=getattr(suggestion, "regulation_id", "") or "",
                    role_match_run_id=getattr(suggestion, "role_match_run_id", "") or "",
                    qa_history=qa_history,
                )
            except ApiError as exc:
                self._passport_failed.emit(exc.message)
                return
            except Exception as exc:  # noqa: BLE001
                self._passport_failed.emit(f"Не удалось обновить паспорт: {exc}")
                return
            self._passport_ready.emit(updated)

        Thread(target=run, daemon=True).start()

    def _show_passport_result(self, result: object) -> None:
        if isinstance(result, PassportSession):
            if result.draft_id:
                self._current_passport_draft_id = result.draft_id
            try:
                self._page_passport.apply_session(result)
            except Exception as exc:  # noqa: BLE001
                self._page_passport.show_error(f"Не удалось показать паспорт: {exc}")
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

    def _on_schedule_requested(self, record: object) -> None:
        if not isinstance(record, WorkflowRecord):
            return

        def run() -> None:
            try:
                draft = self._api.propose_schedule_draft(record.id)
            except ApiError:
                goal = record.plan.goal if record.plan else ""
                draft = ScheduleDraft(name=record.title or "ИИ-агент", goal=goal or "")
            self._schedule_draft_ready.emit((record, draft))

        Thread(target=run, daemon=True).start()

    def _on_board_schedule_requested(self, workflow_id: str) -> None:
        wid = (workflow_id or "").strip()
        if not wid:
            return
        self._schedule_from_agents = True
        from app.orchestrator.agents import local_workflow

        local = local_workflow(wid)
        if local is not None:
            goal = local.plan.goal if local.plan else ""
            self._schedule_draft_ready.emit((local, ScheduleDraft(name=local.title or "ИИ-агент", goal=goal or "")))
            return

        def run() -> None:
            try:
                record = self._api.get_workflow(wid)
                try:
                    draft = self._api.propose_schedule_draft(record.id)
                except ApiError:
                    goal = record.plan.goal if record.plan else ""
                    draft = ScheduleDraft(name=record.title or "ИИ-агент", goal=goal or "")
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._schedule_draft_ready.emit((record, draft))

        Thread(target=run, daemon=True).start()

    def _on_board_schedule_run(self, workflow_id: str, at_iso: str) -> None:
        wid = (workflow_id or "").strip()
        if not wid or not (at_iso or "").strip():
            return

        from app.orchestrator.agents import is_local_workflow

        if is_local_workflow(wid):
            return

        def run() -> None:
            try:
                self._api.create_timed_trigger(wid, at=at_iso, message="Плановый запуск")
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._board_reload.emit()

        Thread(target=run, daemon=True).start()

    def _on_create_agent_from_board(self) -> None:
        self.sidebar.set_active_key("create")
        self._pages.setCurrentIndex(self._page_index["create"])

    def _on_schedule_back(self) -> None:
        if self._schedule_from_agents:
            self._schedule_from_agents = False
            self.sidebar.set_active_key("agents", animate=False)
            self._pages.setCurrentIndex(self._page_index["agents"])
            return
        self._pages.setCurrentIndex(self._page_index["workflows"])

    def _show_schedule_page(self, payload: object) -> None:
        record, draft = payload if isinstance(payload, tuple) else (None, None)
        if not isinstance(record, WorkflowRecord):
            return
        self._page_schedule.load(record, draft if isinstance(draft, ScheduleDraft) else ScheduleDraft())
        self._pages.setCurrentIndex(self._page_index["schedule"])

    def _on_schedule_save(self, record: object, draft: object) -> None:
        if not isinstance(record, WorkflowRecord) or not isinstance(draft, ScheduleDraft):
            return
        self._page_schedule.set_busy(True)
        wid = record.id
        from_agents = self._schedule_from_agents and str(getattr(record, "phase", "") or "") == "done"

        def run() -> None:
            try:
                local = dict(record.local_run or {})
                local["schedule_draft"] = {
                    "name": draft.name,
                    "goal": draft.goal,
                    "triggers": [
                        {
                            "kind": item.kind,
                            "message": item.message,
                            "interval_value": item.interval_value,
                            "interval_unit": item.interval_unit,
                            "condition": item.condition,
                            "at": item.at,
                            "once": item.once,
                        }
                        for item in draft.triggers
                    ],
                }
                updated = self._api.update_workflow_local_run(wid, local)
                if from_agents:
                    for item in self._api.list_triggers():
                        if str(item.get("workflow_id") or "") != wid:
                            continue
                        if not item.get("enabled"):
                            continue
                        trigger_id = str(item.get("id") or "")
                        if trigger_id:
                            self._api.cancel_trigger(trigger_id)
                    for spec in draft.triggers:
                        if isinstance(spec, ScheduleTriggerSpec):
                            self._api.create_trigger(wid, spec, message=spec.message or draft.goal)
                    self._schedule_save_ready.emit(updated)
                    return
            except ApiError as exc:
                self._schedule_failed.emit(exc.message)
                return
            self._kpi_preview_ready.emit(updated)

        Thread(target=run, daemon=True).start()

    def _show_kpi_preview(self, record: object) -> None:
        self._page_schedule.set_busy(False)
        if not isinstance(record, WorkflowRecord):
            return
        self._page_kpi_preview.start(record)
        self._pages.setCurrentIndex(self._page_index["kpi_preview"])

    def _on_kpi_back(self) -> None:
        record = self._page_kpi_preview.current_record()
        draft = ScheduleDraft()
        if isinstance(record, WorkflowRecord):
            raw = (record.local_run or {}).get("schedule_draft")
            if isinstance(raw, dict):
                draft = _parse_schedule_draft(raw)
            self._page_schedule.load(record, draft)
        self._pages.setCurrentIndex(self._page_index["schedule"])

    def _on_kpi_confirm(self, record: object) -> None:
        if not isinstance(record, WorkflowRecord):
            return
        self._page_kpi_preview.set_busy(True)
        wid = record.id

        def run() -> None:
            try:
                published = self._api.confirm_workflow_kpi(wid)
                raw = (published.local_run or {}).get("schedule_draft")
                draft = _parse_schedule_draft(raw) if isinstance(raw, dict) else ScheduleDraft()
                for spec in draft.triggers:
                    self._api.create_trigger(published.id, spec, message=spec.message or draft.goal)
            except ApiError as exc:
                self._schedule_failed.emit(exc.message)
                return
            self._schedule_save_ready.emit(published)

        Thread(target=run, daemon=True).start()

    def _show_schedule_saved(self, record: object) -> None:
        self._page_schedule.set_busy(False)
        self._page_kpi_preview.set_busy(False)
        self._schedule_from_agents = False
        if isinstance(record, WorkflowRecord):
            self._page_workflows.saved.emit(record.id)
            self._on_workflow_record_saved(record)
        self.sidebar.set_active_key("agents", animate=False)
        self._pages.setCurrentIndex(self._page_index["agents"])
        self._load_agent_drafts()

    def _show_schedule_error(self, message: str) -> None:
        self._page_schedule.set_busy(False)
        self._page_kpi_preview.set_busy(False)
        title = "KPI агента" if self._pages.currentIndex() == self._page_index["kpi_preview"] else "Паспорт агента"
        QMessageBox.warning(self, title, message)

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
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._board_reload.emit()

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
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._board_reload.emit()

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
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._board_reload.emit()

        Thread(target=run, daemon=True).start()

    def _on_stop_published_agent(self, workflow_id: str) -> None:
        from app.orchestrator.agents import is_local_workflow

        if is_local_workflow(workflow_id):
            return
        answer = QMessageBox.question(
            self,
            "Приостановить агента",
            "Приостановить этого агента? Плановые запуски будут пропускаться, пока вы его не возобновите.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def run() -> None:
            try:
                self._api.stop_workflow_auto_run(workflow_id)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._board_reload.emit()

        Thread(target=run, daemon=True).start()

    def _on_resume_published_agent(self, workflow_id: str) -> None:
        from app.orchestrator.agents import is_local_workflow

        if is_local_workflow(workflow_id):
            return

        def run() -> None:
            try:
                self._api.resume_workflow_auto_run(workflow_id)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._board_reload.emit()

        Thread(target=run, daemon=True).start()

    def _on_delete_published_agent(self, workflow_id: str) -> None:
        answer = QMessageBox.question(
            self,
            "Удалить ИИ-агента",
            "Удалить этого опубликованного ИИ-агента? Это действие нельзя отменить.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._deleted_workflow_ids.add(workflow_id)
        current = getattr(self._page_agents, "_board", None)
        if isinstance(current, WorkflowBoard):
            cleaned = without_deleted_workflows(current, self._deleted_workflow_ids)
            self._page_agents.set_board(cleaned)
            self._page_orchestrator.set_bound_agents(cleaned.agents)
        from app.orchestrator.agents import is_local_workflow

        if is_local_workflow(workflow_id):
            return

        def run() -> None:
            try:
                self._api.delete_workflow(workflow_id)
            except ApiError as exc:
                self._deleted_workflow_ids.discard(workflow_id)
                self._readiness_failed.emit(exc.message)
                self._board_reload.emit()
                return
            self._board_reload.emit()

        Thread(target=run, daemon=True).start()

    def show_live_agent(self, workflow_id: str) -> None:
        """Открыть живой прогон агента, не историю и не новый чат."""
        from app.tools.hitl import attach_pending_for

        wid = (workflow_id or "").strip()
        if not wid:
            return
        run_rec = getattr(self._page_agent_run, "_workflow", None)
        if run_rec is not None and str(getattr(run_rec, "id", "") or "") == wid:
            self.sidebar.set_active_key("agents", animate=False)
            self._pages.setCurrentIndex(self._page_index["agent_run"])
            attach_pending_for(wid)
            return
        wf_rec = getattr(self._page_workflows, "_record", None)
        if wf_rec is not None and str(getattr(wf_rec, "id", "") or "") == wid:
            self._pages.setCurrentIndex(self._page_index["workflows"])
            attach_pending_for(wid)
            return
        self.navigate_to_agent_run(wid)

    def navigate_to_agent_run(
        self,
        workflow_id: str,
        run_id: str = "",
        *,
        start_demo: bool = False,
    ) -> None:
        if (run_id or "").strip():
            self.navigate_to_agent_history(workflow_id, run_id)
            return
        wid = (workflow_id or "").strip()
        if not wid:
            return
        from app.orchestrator.agents import local_workflow

        record = local_workflow(wid)
        if record is not None:
            self._published_agent_ready.emit(record)
            return
        self._pending_start_demo = bool(start_demo)
        self._pages.setCurrentIndex(self._page_index["loading"])

        def run() -> None:
            try:
                record = self._api.get_workflow(wid)
            except ApiError as exc:
                self._pending_start_demo = False
                self._readiness_failed.emit(exc.message)
                return
            if str(getattr(record, "phase", "") or "") == "done":
                self._pending_start_demo = False
                self._published_agent_ready.emit(record)
            else:
                self._workflow_page_ready.emit(record)

        Thread(target=run, daemon=True).start()

    def navigate_to_agent_history(self, workflow_id: str, run_id: str = "") -> None:
        wid = (workflow_id or "").strip()
        if not wid:
            return
        from app.orchestrator.agents import local_workflow

        local = local_workflow(wid)
        if local is not None:
            self._agent_history_ready.emit((local.title, wid, [], None))
            return

        def run() -> None:
            try:
                record = self._api.get_workflow(wid)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            if str(getattr(record, "phase", "") or "") != "done":
                self._workflow_page_ready.emit(record)
                return
            try:
                runs = self._api.list_agent_runs(wid)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            wanted = (run_id or "").strip()
            if not wanted and runs:
                wanted = runs[0].id
            detail = None
            if wanted:
                try:
                    detail = self._api.get_agent_run(wid, wanted)
                except ApiError:
                    detail = next((item for item in runs if item.id == wanted), None)
            self._agent_history_ready.emit((record.title, wid, runs, detail))

        Thread(target=run, daemon=True).start()

    def _on_run_published_agent(self, workflow_id: str) -> None:
        self.navigate_to_agent_run(workflow_id)

    def _on_agent_history_requested(self, workflow_id: str, title: str) -> None:
        from app.orchestrator.agents import local_workflow

        if local_workflow(workflow_id) is not None:
            self._agent_history_ready.emit((title, workflow_id, []))
            return

        def run() -> None:
            try:
                runs = self._api.list_agent_runs(workflow_id)
            except ApiError as exc:
                self._readiness_failed.emit(exc.message)
                return
            self._agent_history_ready.emit((title, workflow_id, runs))

        Thread(target=run, daemon=True).start()

    def _on_calendar_run_requested(self, workflow_id: str, run_id: str) -> None:
        self.navigate_to_agent_history(workflow_id, run_id)

    def _on_group_runs_requested(self, events: object) -> None:
        items = events if isinstance(events, list) else []
        self._page_group_runs.show_group(items)
        self.sidebar.set_active_key("agents", animate=False)
        self._pages.setCurrentIndex(self._page_index["agent_group_runs"])

    def _show_agent_history(self, payload: object) -> None:
        title, workflow_id, runs = ("ИИ-агент", "", [])
        detail = None
        if isinstance(payload, tuple) and len(payload) >= 3:
            title = str(payload[0] or "ИИ-агент")
            workflow_id = str(payload[1] or "")
            runs = list(payload[2] or [])
            if len(payload) >= 4:
                detail = payload[3]
        elif isinstance(payload, tuple) and len(payload) >= 2:
            title = str(payload[0] or "ИИ-агент")
            runs = list(payload[1] or [])
        self.sidebar.set_active_key("agents", animate=False)
        if detail is not None:
            self._page_history.open_run(
                title=title,
                workflow_id=workflow_id,
                runs=runs,
                detail=detail,
            )
        else:
            self._page_history.show_history(title=title, workflow_id=workflow_id, runs=runs)
        self._pages.setCurrentIndex(self._page_index["agent_history"])


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
