from __future__ import annotations

from threading import Thread

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QMainWindow, QMessageBox, QStackedWidget, QWidget

from app.agent.harness import CardService
from app.agent.prompts import ui_spec_has_open_questions
from app.models import Card, UiSpec
from app.storage.repository import CardRepository
from app.ui.pages.clarify_page import ClarifyPage
from app.ui.pages.create_page import CreatePage
from app.ui.pages.home_page import HomePage
from app.ui.pages.workspace_page import WorkspacePage


class MainWindow(QMainWindow):
    setup_ready = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MainWindow")
        self.setWindowTitle("RegAgent")
        self.resize(1280, 800)

        self._service = CardService(CardRepository())
        self._pending_card: Card | None = None
        self._pending_path: str | None = None
        self._pending_clarifications: dict[str, str] | None = None

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self._home = HomePage()
        self._create = CreatePage()
        self._clarify = ClarifyPage()
        self._workspace = WorkspacePage()

        self._stack.addWidget(self._home)
        self._stack.addWidget(self._create)
        self._stack.addWidget(self._clarify)
        self._stack.addWidget(self._workspace)

        self._home.create_requested.connect(self._go_create)
        self._home.open_requested.connect(self._open_card)
        self._home.delete_requested.connect(self._delete_card)

        self._create.analyze_requested.connect(self._analyze_regulation)
        self._clarify.submitted.connect(self._clarify_submitted)
        self._clarify.cancelled.connect(lambda: self._show_page("home"))

        self._workspace.back_requested.connect(self._go_home)
        self._workspace.failed.connect(self._show_error)
        self._workspace.agent_ready.connect(self._on_agent_ready)

        self.setup_ready.connect(self._on_setup_ready)

        self._refresh_home()

    def _show_page(self, name: str) -> None:
        index = {"home": 0, "create": 1, "clarify": 2, "workspace": 3}[name]
        self._stack.setCurrentIndex(index)
        if name == "home":
            self._refresh_home()

    def _go_create(self) -> None:
        self._create.reset()
        self._pending_path = None
        self._pending_clarifications = None
        self._show_page("create")

    def _go_home(self) -> None:
        if self._pending_card and self._pending_card.cursor_agent_id:
            self._service.save_card(self._pending_card)
        self._pending_card = None
        self._show_page("home")

    def _refresh_home(self) -> None:
        self._home.set_cards(self._service.list_cards())

    def _analyze_regulation(self) -> None:
        path = self._create.selected_path()
        if not path:
            return
        self._pending_path = path
        self._pending_clarifications = None
        Thread(target=self._run_setup, args=(path, None), daemon=True).start()

    def _clarify_submitted(self, answers: dict[str, str]) -> None:
        if not self._pending_path:
            self._show_page("home")
            return
        self._pending_clarifications = answers
        Thread(
            target=self._run_setup,
            args=(self._pending_path, answers),
            daemon=True,
        ).start()

    def _run_setup(self, path: str, clarifications: dict[str, str] | None) -> None:
        events: list[dict] = []

        def on_event(ev: dict) -> None:
            events.append(ev)

        try:
            card, spec = self._service.create_from_regulation(
                path,
                clarifications=clarifications,
                existing=self._pending_card,
                on_event=on_event,
            )
            payload = {"ok": True, "card": card, "spec": spec, "saved": not ui_spec_has_open_questions(spec) or bool(clarifications)}
            self.setup_ready.emit(payload)
        except Exception as exc:
            self.setup_ready.emit({"ok": False, "error": str(exc)})

    def _on_setup_ready(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if not payload.get("ok"):
            self._show_error(str(payload.get("error") or "Ошибка setup"))
            return
        card = payload.get("card")
        spec = payload.get("spec")
        if not isinstance(card, Card):
            return
        if isinstance(spec, UiSpec) and ui_spec_has_open_questions(spec) and not self._pending_clarifications:
            self._pending_card = card
            self._clarify.set_spec(spec)
            self._show_page("clarify")
            return
        self._service.save_card(card)
        self._pending_card = None
        self._open_card(card.id)

    def _open_card(self, card_id: str) -> None:
        card = self._service.get(card_id)
        if card is None:
            self._show_error("Карточка не найдена")
            return
        self._workspace.load_card(card)
        self._show_page("workspace")

    def _delete_card(self, card_id: str) -> None:
        reply = QMessageBox.question(
            self,
            "Удалить карточку?",
            "Действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._service.delete(card_id)
        self._refresh_home()

    def _on_agent_ready(self, card_id: str, agent_id: str) -> None:
        self._service.update_agent_id(card_id, agent_id)

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "RegAgent", message)
