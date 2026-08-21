from __future__ import annotations

from threading import Thread

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.agent.pipeline import CardPipelineService, PipelineError
from app.api_client import ApiClient, UserProfile
from app.models import Card, phase_page_name
from app.storage.repository import CardRepository
from app.storage.session_log import load_session_log
from app.ui.pages.clarify_page import ClarifyPage
from app.ui.pages.create_page import CreatePage
from app.ui.pages.demo_page import DemoPage
from app.ui.pages.home_page import HomePage
from app.ui.pages.kpi_page import KpiPage
from app.ui.pages.passport_page import PassportPage
from app.ui.pages.process_page import ProcessPickerPage
from app.ui.pages.review_page import ReviewPage
from app.ui.pages.schedule_page import SchedulePage
from app.ui.pages.workspace_page import WorkspacePage, show_history_dialog
from app.ui.theme import COLOR_CONTENT_BG, CONTENT_PADDING_TOP, CONTENT_PADDING_X
from app.ui.widgets.app_dialog import confirm_dialog, info_dialog
from app.ui.widgets.pipeline_progress import (
    ADVANCE_MESSAGES,
    CREATION_FLOW_PAGES,
    PipelineAdvanceBanner,
    PipelineBusyPanel,
    PipelineStepper,
    status_for_pipeline_step,
)
from app.ui.widgets.sidebar import GlassSidebar
from app.ui.widgets.user_menu import UserMenuHeader


class MainContentWidget(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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
    pipeline_ready = Signal(object)
    pipeline_progress = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._user: UserProfile | None = None
        self._pipeline = CardPipelineService(CardRepository())
        self._active_card: Card | None = None
        self._pipeline_busy = False
        self._current_flow_page = ""
        self._pending_advance: str | None = None

        self.sidebar = GlassSidebar(self)
        self.sidebar.page_changed.connect(self._on_sidebar_page)

        self._home = HomePage()
        self._create = CreatePage()
        self._review = ReviewPage()
        self._process = ProcessPickerPage()
        self._passport = PassportPage()
        self._clarify = ClarifyPage()
        self._demo = DemoPage()
        self._schedule = SchedulePage()
        self._kpi = KpiPage()
        self._workspace = WorkspacePage()

        self._pages = QStackedWidget()
        self._page_index = {
            "agents": self._pages.addWidget(self._home),
            "create": self._pages.addWidget(self._create),
            "review": self._pages.addWidget(self._review),
            "process": self._pages.addWidget(self._process),
            "passport": self._pages.addWidget(self._passport),
            "clarify": self._pages.addWidget(self._clarify),
            "demo": self._pages.addWidget(self._demo),
            "schedule": self._pages.addWidget(self._schedule),
            "kpi": self._pages.addWidget(self._kpi),
            "workspace": self._pages.addWidget(self._workspace),
        }

        self._home.open_requested.connect(self._open_card)
        self._home.create_requested.connect(self._go_create)
        self._home.delete_requested.connect(self._delete_card)
        self._home.continue_requested.connect(self._continue_draft)
        self._home.history_requested.connect(self._open_history)
        self._create.analyze_requested.connect(self._analyze_regulation)
        self._create.create_regulation_requested.connect(self._on_create_regulation_ai)
        self._review.confirmed.connect(self._review_confirmed)
        self._review.cancelled.connect(self._go_home)
        self._process.selected.connect(self._process_selected)
        self._process.cancelled.connect(self._navigate_card_phase)
        self._passport.continue_requested.connect(self._passport_to_playbook)
        self._passport.cancelled.connect(self._navigate_card_phase)
        self._clarify.submitted.connect(self._passport_clarify_submitted)
        self._clarify.cancelled.connect(self._navigate_card_phase)
        self._demo.run_demo_requested.connect(self._run_demo)
        self._demo.publish_requested.connect(self._publish_card)
        self._demo.cancelled.connect(self._navigate_card_phase)
        self._schedule.finished.connect(self._schedule_done)
        self._schedule.skipped.connect(self._schedule_done)
        self._workspace.back_requested.connect(self._go_home)
        self._workspace.agent_ready.connect(self._on_agent_ready)
        self.pipeline_ready.connect(self._on_pipeline_ready)
        self.pipeline_progress.connect(self._on_pipeline_progress)

        self._pipeline_stepper = PipelineStepper()
        self._pipeline_busy_panel = PipelineBusyPanel()
        self._pipeline_advance = PipelineAdvanceBanner()

        self.user_menu = UserMenuHeader(self)
        self.user_menu.logout_requested.connect(self.logout_requested.emit)
        self.user_menu.history_requested.connect(self._workspace.show_session_history)

        self._content = MainContentWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(
            CONTENT_PADDING_X,
            CONTENT_PADDING_TOP,
            CONTENT_PADDING_X,
            30,
        )
        content_layout.addWidget(self._pipeline_stepper)
        content_layout.addWidget(self._pipeline_busy_panel)
        content_layout.addWidget(self._pipeline_advance)
        content_layout.addWidget(self._pages, 1)
        self._pipeline_stepper.hide()
        self._sync_pipeline_chrome("agents")

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
        self._collapse_btn.setStyleSheet(
            """
            QPushButton {
                color: #EAF7F3; background: rgba(6, 40, 34, 0.94);
                border: 1px solid rgba(255,255,255,0.18); border-radius: 14px; font-size: 18px;
            }
            QPushButton:hover { background: rgba(8, 70, 58, 0.98); }
            """
        )
        self._collapse_btn.setToolTip("Свернуть меню")
        self._collapse_btn.clicked.connect(self.sidebar.toggle_collapsed)
        self.sidebar.collapse_toggled.connect(self._on_sidebar_collapse)
        self.sidebar.set_active_key("agents", animate=False)
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
            x = self.sidebar.width() - btn.width() - 12
        y = self.height() - btn.height() - 22
        btn.move(max(0, x), max(0, y))
        btn.raise_()

    def _position_user_menu(self) -> None:
        menu = self.user_menu
        menu.adjustSize()
        right = self._content.width() - CONTENT_PADDING_X
        menu.move(
            max(0, right - menu.width()),
            max(0, CONTENT_PADDING_TOP),
        )
        menu.raise_()

    def _on_sidebar_collapse(self, collapsed: bool) -> None:
        self._collapse_btn.setText("›" if collapsed else "‹")
        self._collapse_btn.setToolTip("Развернуть меню" if collapsed else "Свернуть меню")
        QTimer.singleShot(0, self._position_overlays)

    def set_user(self, user: UserProfile) -> None:
        self._user = user
        self.user_menu.avatar.set_default_logo()
        self.user_menu.set_user(fio=user.fio, position=user.position)
        self._refresh_home()

    def set_logout_visible(self, visible: bool) -> None:
        self.user_menu.set_logout_visible(visible)

    def _on_sidebar_page(self, key: str) -> None:
        if key in ("agents", "create", "kpi"):
            self._show_page(key)

    def _show_page(self, name: str) -> None:
        idx = self._page_index.get(name)
        if idx is None:
            return
        self._pages.setCurrentIndex(idx)
        self._current_flow_page = name
        self._sync_pipeline_chrome(name)
        self.user_menu.set_history_visible(name == "workspace")
        QTimer.singleShot(0, self._position_overlays)
        if name == "agents":
            self._home.show_agents()
            self._refresh_home()
        elif name == "kpi":
            self._refresh_kpi()

    def _go_create(self) -> None:
        self._create.reset()
        self._active_card = None
        self._show_page("create")
        self.sidebar.set_active_key("create", animate=False)

    def _go_home(self) -> None:
        if self._active_card is not None:
            self._pipeline.save(self._active_card)
        self._active_card = None
        self._pending_advance = None
        self._pipeline_advance.hide_banner()
        self._show_page("agents")

    def _refresh_home(self) -> None:
        all_cards = self._pipeline.list_cards()
        published = [c for c in all_cards if c.phase == "published"]
        drafts = [c for c in all_cards if c.phase != "published"]
        if self._active_card is not None and self._active_card.phase != "published":
            if not any(c.id == self._active_card.id for c in drafts):
                drafts.insert(0, self._active_card)
        self._home.set_cards(published, drafts)

    def _refresh_kpi(self) -> None:
        self._kpi.refresh(self._pipeline.list_cards())

    def _on_create_regulation_ai(self) -> None:
        info_dialog(
            self,
            "Создание регламента",
            "Создание регламента с помощью ИИ пока доступно только в turbobot (backend). "
            "В RegAgent загрузите готовый регламент через карточку «Загрузить регламент».",
        )

    def _continue_draft(self, card_id: str) -> None:
        card = self._pipeline.get(card_id)
        if card is None and self._active_card is not None and self._active_card.id == card_id:
            card = self._active_card
        if card is None:
            info_dialog(self, "RegAgent", "Черновик не найден")
            return
        self._active_card = card
        self._navigate_card_phase()

    def _open_history(self, card_id: str, _title: str) -> None:
        if self._workspace.current_card_id() == card_id and self._workspace.history_entries():
            entries = self._workspace.history_entries()
        else:
            card = self._pipeline.get(card_id)
            workspace = card.workspace_dir if card is not None else ""
            entries = load_session_log(card_id, workspace)
        show_history_dialog(self, entries)

    def _analyze_regulation(self) -> None:
        path = self._create.selected_path()
        if not path:
            return
        self._set_pipeline_busy(True, status_for_pipeline_step("intake"))
        Thread(target=self._run_intake, args=(path,), daemon=True).start()

    def _run_intake(self, path: str) -> None:
        try:
            card = self._pipeline.intake_regulation(path, existing=self._active_card)
            self.pipeline_ready.emit({"ok": True, "card": card, "step": "intake"})
        except Exception as exc:
            self.pipeline_ready.emit({"ok": False, "error": str(exc)})

    def _review_confirmed(self) -> None:
        if self._active_card is None:
            return
        self._run_pipeline_step("functions")

    def _process_selected(self, group_id: str) -> None:
        if self._active_card is None:
            return
        self._active_card = self._pipeline.select_function_group(self._active_card, group_id)
        self._process.set_actions_enabled(False)
        self._run_pipeline_step("passport")

    def _passport_to_playbook(self) -> None:
        if self._active_card is None:
            return
        self._active_card = self._passport.apply_field_values(self._active_card)
        self._pipeline.save(self._active_card)
        questions = self._passport.open_questions()
        if questions:
            self._clarify.set_spec_questions(questions)
            self._pages.setCurrentIndex(self._page_index["clarify"])
            return
        self._run_pipeline_step("playbook")

    def _passport_clarify_submitted(self, answers: dict[str, str]) -> None:
        if self._active_card is None:
            return
        self._active_card = self._pipeline.answer_passport_questions(self._active_card, answers)
        self._run_pipeline_step("playbook")

    def _run_demo(self) -> None:
        if self._active_card is None:
            return
        steps = max(1, len(self._active_card.playbook_draft.steps))
        self._set_pipeline_busy(True, f"Пробный прогон (шаг 1 из {steps})…")
        self._demo.clear_feed()
        card = self._active_card

        def worker() -> None:
            try:
                updated = self._pipeline.run_demo(card, on_event=self._emit_pipeline_progress)
                self.pipeline_ready.emit({"ok": True, "card": updated, "step": "demo"})
            except Exception as exc:
                self.pipeline_ready.emit({"ok": False, "error": str(exc), "step": "demo"})

        Thread(target=worker, daemon=True).start()

    def _publish_card(self) -> None:
        if self._active_card is None:
            return
        try:
            self._active_card = self._pipeline.publish(self._active_card)
        except PipelineError as exc:
            info_dialog(self, "RegAgent", str(exc))
            return
        self._pages.setCurrentIndex(self._page_index["schedule"])
        self._schedule.set_card(self._active_card)

    def _schedule_done(self) -> None:
        if self._active_card is not None:
            self._active_card = self._pipeline.advance_after_schedule(self._active_card)
            self._open_card(self._active_card.id)
        else:
            self._go_home()

    def _run_pipeline_step(self, step: str) -> None:
        if self._active_card is None:
            return
        self._set_pipeline_busy(True, status_for_pipeline_step(step))
        card = self._active_card
        Thread(target=self._pipeline_worker, args=(card, step), daemon=True).start()

    def _emit_pipeline_progress(self, event: dict) -> None:
        self.pipeline_progress.emit(event)

    def _pipeline_worker(self, card: Card, step: str) -> None:
        try:
            if step == "functions":
                updated = self._pipeline.run_functions(card, on_event=self._emit_pipeline_progress)
            elif step == "passport":
                updated = self._pipeline.run_passport(card, on_event=self._emit_pipeline_progress)
            elif step == "playbook":
                updated = self._pipeline.run_playbook_draft(card, on_event=self._emit_pipeline_progress)
            else:
                updated = card
            self.pipeline_ready.emit({"ok": True, "card": updated, "step": step})
        except Exception as exc:
            self.pipeline_ready.emit({"ok": False, "error": str(exc), "step": step})

    def _set_pipeline_busy(self, busy: bool, message: str = "") -> None:
        self._pipeline_busy = busy
        phase = self._active_card.phase if self._active_card is not None else "intake"
        if busy:
            step = self._busy_step_from_message(message)
            if step:
                phase = step
        self._pipeline_stepper.set_phase(phase, busy=busy)
        if busy:
            self._pipeline_busy_panel.show_message(message or "ИИ обрабатывает запрос…")
            self._pipeline_advance.hide_banner()
        else:
            self._pipeline_busy_panel.hide_panel()
        self._create.set_processing(busy and self._current_flow_page == "create")
        self._review.set_actions_enabled(not busy)
        self._process.set_actions_enabled(not busy)
        self._passport.set_actions_enabled(not busy)
        self._clarify.set_actions_enabled(not busy)
        self._demo.set_busy(busy)
        self._schedule.set_actions_enabled(not busy)

    @staticmethod
    def _busy_step_from_message(message: str) -> str | None:
        lowered = (message or "").casefold()
        if "функц" in lowered:
            return "functions"
        if "паспорт" in lowered or "уточн" in lowered:
            return "passport"
        if "сценар" in lowered or "сборк" in lowered:
            return "design"
        if "пробный" in lowered or "демо" in lowered:
            return "demo"
        if "документ" in lowered or "распозна" in lowered:
            return "intake"
        return None

    def _sync_pipeline_chrome(self, page_name: str) -> None:
        in_flow = page_name in CREATION_FLOW_PAGES
        self._pipeline_stepper.setVisible(in_flow)
        if not in_flow:
            self._pipeline_busy_panel.hide_panel()
            self._pipeline_advance.hide_banner()
            return
        phase = self._active_card.phase if self._active_card is not None else "intake"
        if page_name == "create":
            phase = "intake"
        elif page_name == "clarify":
            phase = "readiness"
        elif page_name == "process":
            phase = "functions"
        elif page_name == "demo" and self._active_card is not None and self._active_card.phase == "design":
            phase = "design"
        self._pipeline_stepper.set_phase(phase, busy=self._pipeline_busy)
        if self._pending_advance and not self._pipeline_busy:
            self._pipeline_advance.show_message(self._pending_advance)
            self._pending_advance = None

    def _on_pipeline_progress(self, event: object) -> None:
        if not isinstance(event, dict):
            return
        et = event.get("type")
        text = str(event.get("text") or "").strip()
        if et in {"phase_start", "substep"} and text:
            self._pipeline_busy_panel.show_message(text)
            phase = str(event.get("phase") or "")
            if phase:
                self._pipeline_stepper.set_phase(phase, busy=True)
            elif self._active_card is not None:
                self._pipeline_stepper.set_phase(self._active_card.phase, busy=True)
        elif et == "status" and text:
            self._pipeline_busy_panel.show_message(text)
        if self._current_flow_page == "demo":
            self._demo.handle_pipeline_event(event)

    def _on_pipeline_ready(self, payload: object) -> None:
        self._set_pipeline_busy(False)
        if not isinstance(payload, dict):
            return
        if not payload.get("ok"):
            info_dialog(self, "RegAgent", str(payload.get("error") or "Ошибка pipeline"))
            return
        card = payload.get("card")
        if not isinstance(card, Card):
            return
        step = str(payload.get("step") or "")
        advance = ADVANCE_MESSAGES.get(step, "")
        if advance:
            self._pending_advance = advance
            self._pipeline_advance.show_message(advance)
            if step == "functions" and card.phase == "passport":
                self._review.show_advance("Функции определены — формируем паспорт…")
            elif step == "passport":
                self._passport.show_advance("Паспорт готов — проверьте поля")
            elif step == "playbook":
                self._demo.show_advance("Сценарий собран — запустите пробный прогон")
        self._active_card = card
        self._navigate_card_phase()

    def _navigate_card_phase(self) -> None:
        if self._active_card is None:
            self._go_home()
            return
        card = self._active_card
        page = phase_page_name(card.phase)
        if page == "review":
            self._review.set_card(card)
        elif page == "process":
            self._process.set_card(card)
        elif page == "passport":
            self._passport.set_card(card)
            if card.phase == "readiness" and card.passport.questions:
                self._clarify.set_spec_questions(card.passport.questions)
                idx = self._page_index.get("clarify")
                if idx is not None:
                    self._pages.setCurrentIndex(idx)
                self._current_flow_page = "clarify"
                self._sync_pipeline_chrome("clarify")
                return
        elif page == "demo":
            self._demo.set_card(card)
        elif page == "schedule":
            self._schedule.set_card(card)
        elif page == "workspace":
            self._open_card(card.id)
            return
        elif page == "create":
            page = "review"
            self._review.set_card(card)
        idx = self._page_index.get(page)
        if idx is not None:
            self._pages.setCurrentIndex(idx)
        self._current_flow_page = page if page in CREATION_FLOW_PAGES else self._current_flow_page
        self._sync_pipeline_chrome(page if page in CREATION_FLOW_PAGES else self._current_flow_page)

    def _open_card(self, card_id: str, *, show_history: bool = False) -> None:
        card = self._pipeline.get(card_id)
        if card is None:
            info_dialog(self, "RegAgent", "Карточка не найдена")
            return
        if card.phase != "published":
            self._active_card = card
            self._navigate_card_phase()
            return
        self._workspace.load_card(card, show_history=show_history)
        self._pages.setCurrentIndex(self._page_index["workspace"])
        self._current_flow_page = "workspace"
        self._sync_pipeline_chrome("workspace")
        self.user_menu.set_history_visible(True)
        QTimer.singleShot(0, self._position_overlays)

    def _delete_card(self, card_id: str) -> None:
        if not confirm_dialog(
            self,
            "Удалить карточку?",
            "Действие необратимо.",
            primary="Удалить",
            danger=True,
        ):
            return
        if self._active_card is not None and self._active_card.id == card_id:
            self._active_card = None
        self._pipeline.delete(card_id)
        self._refresh_home()

    def _on_agent_ready(self, card_id: str, agent_id: str) -> None:
        self._pipeline.repo.update_agent_id(card_id, agent_id)
