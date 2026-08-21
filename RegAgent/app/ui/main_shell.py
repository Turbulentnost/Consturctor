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

from app.agent.harness import CardService
from app.agent.prompts import ui_spec_has_open_questions
from app.api_client import ApiClient, UserProfile
from app.models import Card, UiSpec
from app.storage.repository import CardRepository
from app.ui.pages.clarify_page import ClarifyPage
from app.ui.pages.create_page import CreatePage
from app.ui.pages.home_page import HomePage
from app.ui.pages.kpi_page import KpiPage
from app.storage.session_log import load_session_log
from app.ui.pages.workspace_page import WorkspacePage, show_history_dialog
from app.ui.theme import COLOR_CONTENT_BG, CONTENT_PADDING_TOP, CONTENT_PADDING_X
from app.ui.widgets.app_dialog import confirm_dialog, info_dialog
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
    setup_ready = Signal(object)

    def __init__(self, api: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._user: UserProfile | None = None
        self._service = CardService(CardRepository())
        self._pending_card: Card | None = None
        self._pending_path: str | None = None
        self._pending_clarifications: dict[str, str] | None = None

        self.sidebar = GlassSidebar(self)
        self.sidebar.page_changed.connect(self._on_sidebar_page)

        self._home = HomePage()
        self._create = CreatePage()
        self._clarify = ClarifyPage()
        self._kpi = KpiPage()
        self._workspace = WorkspacePage()

        self._pages = QStackedWidget()
        self._page_index = {
            "agents": self._pages.addWidget(self._home),
            "create": self._pages.addWidget(self._create),
            "clarify": self._pages.addWidget(self._clarify),
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
        self._clarify.submitted.connect(self._clarify_submitted)
        self._clarify.cancelled.connect(lambda: self._show_page("agents"))
        self._workspace.back_requested.connect(self._go_home)
        self._workspace.agent_ready.connect(self._on_agent_ready)
        self.setup_ready.connect(self._on_setup_ready)

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
        content_layout.addWidget(self._pages, 1)

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
        self.user_menu.set_history_visible(name == "workspace")
        QTimer.singleShot(0, self._position_overlays)
        if name == "agents":
            self._home.show_agents()
            self._refresh_home()
        elif name == "kpi":
            self._refresh_kpi()

    def _go_create(self) -> None:
        self._create.reset()
        self._pending_path = None
        self._pending_clarifications = None
        self._show_page("create")
        self.sidebar.set_active_key("create", animate=False)

    def _go_home(self) -> None:
        if self._pending_card and self._pending_card.cursor_agent_id:
            self._service.save_card(self._pending_card)
        self._pending_card = None
        self._show_page("agents")

    def _refresh_home(self) -> None:
        all_cards = self._service.list_cards()
        published = [c for c in all_cards if not ui_spec_has_open_questions(c.ui_spec)]
        drafts = [c for c in all_cards if ui_spec_has_open_questions(c.ui_spec)]
        if self._pending_card is not None:
            pending_id = self._pending_card.id
            if not any(c.id == pending_id for c in drafts):
                drafts.insert(0, self._pending_card)
        self._home.set_cards(published, drafts)

    def _published_cards(self) -> list[Card]:
        return [c for c in self._service.list_cards() if not ui_spec_has_open_questions(c.ui_spec)]

    def _refresh_kpi(self) -> None:
        self._kpi.refresh(self._service.list_cards())

    def _on_create_regulation_ai(self) -> None:
        info_dialog(
            self,
            "Создание регламента",
            "Создание регламента с помощью ИИ пока доступно только в turbobot (backend). "
            "В RegAgent загрузите готовый регламент через карточку «Загрузить регламент».",
        )

    def _continue_draft(self, card_id: str) -> None:
        if self._pending_card is not None and self._pending_card.id == card_id:
            self._clarify.set_spec(self._pending_card.ui_spec)
            self._pages.setCurrentIndex(self._page_index["clarify"])
            return
        card = self._service.get(card_id)
        if card is None:
            info_dialog(self, "RegAgent", "Черновик не найден")
            return
        if ui_spec_has_open_questions(card.ui_spec):
            self._pending_card = card
            self._pending_path = card.regulation_path or None
            self._clarify.set_spec(card.ui_spec)
            self._pages.setCurrentIndex(self._page_index["clarify"])
            return
        self._open_card(card_id)

    def _open_history(self, card_id: str, _title: str) -> None:
        if self._workspace.current_card_id() == card_id and self._workspace.history_entries():
            entries = self._workspace.history_entries()
        else:
            card = self._service.get(card_id)
            workspace = card.workspace_dir if card is not None else ""
            entries = load_session_log(card_id, workspace)
        show_history_dialog(self, entries)

    def _analyze_regulation(self) -> None:
        path = self._create.selected_path()
        if not path:
            return
        self._pending_path = path
        self._pending_clarifications = None
        self._create.set_processing(True)
        Thread(target=self._run_setup, args=(path, None), daemon=True).start()

    def _clarify_submitted(self, answers: dict[str, str]) -> None:
        if not self._pending_path:
            self._show_page("agents")
            return
        self._pending_clarifications = answers
        Thread(
            target=self._run_setup,
            args=(self._pending_path, answers),
            daemon=True,
        ).start()

    def _run_setup(self, path: str, clarifications: dict[str, str] | None) -> None:
        try:
            card, spec = self._service.create_from_regulation(
                path,
                clarifications=clarifications,
                existing=self._pending_card,
            )
            payload = {
                "ok": True,
                "card": card,
                "spec": spec,
                "saved": not ui_spec_has_open_questions(spec) or bool(clarifications),
            }
            self.setup_ready.emit(payload)
        except Exception as exc:
            self.setup_ready.emit({"ok": False, "error": str(exc)})

    def _on_setup_ready(self, payload: object) -> None:
        self._create.set_processing(False)
        if not isinstance(payload, dict):
            return
        if not payload.get("ok"):
            info_dialog(self, "RegAgent", str(payload.get("error") or "Ошибка setup"))
            return
        card = payload.get("card")
        spec = payload.get("spec")
        if not isinstance(card, Card):
            return
        if isinstance(spec, UiSpec) and ui_spec_has_open_questions(spec) and not self._pending_clarifications:
            self._pending_card = card
            self._clarify.set_spec(spec)
            self._pages.setCurrentIndex(self._page_index["clarify"])
            return
        self._service.save_card(card)
        self._pending_card = None
        self._open_card(card.id)

    def _open_card(self, card_id: str, *, show_history: bool = False) -> None:
        card = self._service.get(card_id)
        if card is None:
            info_dialog(self, "RegAgent", "Карточка не найдена")
            return
        self._workspace.load_card(card, show_history=show_history)
        self._pages.setCurrentIndex(self._page_index["workspace"])
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
        if self._pending_card is not None and self._pending_card.id == card_id:
            self._pending_card = None
        self._service.delete(card_id)
        self._refresh_home()

    def _on_agent_ready(self, card_id: str, agent_id: str) -> None:
        self._service.update_agent_id(card_id, agent_id)
