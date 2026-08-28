from __future__ import annotations

import sys
from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QMenu, QMessageBox, QStackedWidget, QSystemTrayIcon

from app.agents.headless_runner import HeadlessRunner
from app.api_client import ApiClient, ApiError, LoginResult
from app.chat.test_user import test_login_result
from app.config import auth_skip_login_page, auth_test_user, erp_login, erp_password
from app.notifications.service import NotificationService, show_windows_toast
from app.session_store import clear_session, load_session, save_session
from app.tools.hitl import (
    install_confirm_host,
    notification_opens_live,
    set_away_notify_callback,
)
from app.tools.runtime_api import configure as configure_runtime_api
from app.ui.login_page import LoginPage
from app.ui.main_shell import MainShell
from app.ui.theme import fit_window_minimum, fit_window_size


class AppWindow(QMainWindow):
    def __init__(
        self,
        api: ApiClient | None = None,
        *,
        open_workflow_id: str = "",
        open_run_id: str = "",
        start_demo: bool = False,
    ) -> None:
        super().__init__()
        self.api = api or ApiClient()
        self._force_quit = False
        self._pending_workflow_id = (open_workflow_id or "").strip()
        self._pending_run_id = (open_run_id or "").strip()
        self._pending_start_demo = bool(start_demo)
        self._pending_open_live = False
        self._last_toast_run_id = ""
        from app.chat.test_user import ZHALYBIN_FIO

        self.setWindowTitle(f"turbobot — {ZHALYBIN_FIO}" if auth_test_user() else "turbobot")
        logo = Path(__file__).resolve().parent / "temp" / "logo.png"
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        screen = QApplication.primaryScreen()
        width, height = fit_window_size(screen)
        min_w, min_h = fit_window_minimum(screen)
        self.resize(width, height)
        self.setMinimumSize(min_w, min_h)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self.login_page = LoginPage(self.api)
        self.main_shell = MainShell(self.api)
        self._stack.addWidget(self.login_page)
        self._stack.addWidget(self.main_shell)

        self.login_page.logged_in.connect(self._on_logged_in)
        self.main_shell.logout_requested.connect(self._on_logout)
        if auth_skip_login_page():
            self.main_shell.user_menu.set_logout_visible(False)

        self._notify = NotificationService(self)
        self._runner = HeadlessRunner(self.api, self)
        self._last_toast_workflow_id = ""
        self._setup_tray(logo if logo.exists() else None)
        self._notify.open_workflow_requested.connect(self.open_workflow)
        self._notify.toast_requested.connect(self._on_tray_toast)
        self._notify.inbox_changed.connect(self.main_shell.refresh_notification_badge)
        self._notify.command_received.connect(self._runner.handle_command)
        self._notify.board_updated.connect(self.main_shell.apply_live_board)
        self._notify.tool_requested.connect(self._on_tool_request)
        self._notify.chat_event.connect(self.main_shell.apply_chat_event)
        self._notify.session_kicked.connect(self._on_session_kicked)
        self._runner.toast_requested.connect(self._on_tray_toast)
        install_confirm_host(self)
        set_away_notify_callback(self._on_away_confirmation)

        if auth_skip_login_page():
            if self._try_auto_login():
                return
            self._stack.setCurrentWidget(self.login_page)
            return
        if not self._try_restore_session():
            self._stack.setCurrentWidget(self.login_page)

    def handle_external_command(self, command: str) -> None:
        text = (command or "").strip()
        if text.startswith("start-demo:"):
            workflow_id = text.split(":", 1)[1].strip()
            self.open_workflow(workflow_id, start_demo=True)
            return
        if text.startswith("open-workflow:"):
            rest = text.split(":", 1)[1].strip()
            workflow_id, _, run_id = rest.partition("|")
            self.open_workflow(workflow_id, run_id)
            return
        if text in {"ping", "hide"}:
            if text == "hide":
                self.hide()
            return
        self.reveal()

    def open_workflow(
        self,
        workflow_id: str,
        run_id: str = "",
        *,
        start_demo: bool = False,
    ) -> None:
        wid = (workflow_id or "").strip()
        if not wid:
            return
        self.reveal()
        open_live = notification_opens_live(wid) and not start_demo
        if self._stack.currentWidget() is self.main_shell:
            if start_demo:
                self.main_shell.navigate_to_agent_run(wid, start_demo=True)
            elif open_live:
                self.main_shell.show_live_agent(wid)
            else:
                self.main_shell.navigate_to_agent_history(wid, run_id)
        else:
            self._pending_workflow_id = wid
            self._pending_run_id = (run_id or "").strip()
            self._pending_start_demo = start_demo
            self._pending_open_live = open_live

    def reveal(self) -> None:
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.show()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        if sys.platform == "win32":
            try:
                import ctypes

                hwnd = int(self.winId())
                if hwnd:
                    ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def _agent_title(self, workflow_id: str) -> str:
        wid = (workflow_id or "").strip()
        run = getattr(self.main_shell, "_page_agent_run", None)
        rec = getattr(run, "_workflow", None)
        if rec is not None and str(getattr(rec, "id", "") or "") == wid:
            return (getattr(rec, "title", "") or "").strip() or "агент"
        page = getattr(self.main_shell, "_page_workflows", None)
        rec = getattr(page, "_record", None)
        if rec is not None and (not wid or str(getattr(rec, "id", "") or "") == wid):
            return (getattr(rec, "title", "") or "").strip() or "агент"
        return "агент"

    def _on_away_confirmation(self, workflow_id: str, tool: str, preview: str) -> None:
        name = self._agent_title(workflow_id)
        title = f"Агент «{name}» ждёт вашего подтверждения"
        body = (preview or "").strip() or f"Нужно разрешить «{tool}»."
        if body.lstrip().startswith("{"):
            body = f"Нужно разрешить «{tool}»."
        if len(body) > 180:
            body = body[:177].rstrip() + "…"
        wid = (workflow_id or "").strip()
        QTimer.singleShot(0, lambda: self._deliver_hitl_notice(title, body, wid))

    def _deliver_hitl_notice(self, title: str, body: str, workflow_id: str) -> None:
        shown = show_windows_toast(
            title,
            body,
            workflow_id,
            from_foreground=True,
        )
        if not shown:
            self._on_tray_toast(title, body, workflow_id)
        Thread(
            target=self._post_hitl_inbox,
            args=(title, body, workflow_id),
            daemon=True,
        ).start()

    def _post_hitl_inbox(self, title: str, body: str, workflow_id: str) -> None:
        try:
            self.api.create_inbox_notification(
                title=title,
                body=body,
                workflow_id=workflow_id,
            )
        except ApiError:
            return

    def _setup_tray(self, logo: Path | None) -> None:
        self._tray = QSystemTrayIcon(self)
        if logo is not None:
            self._tray.setIcon(QIcon(str(logo)))
        elif not self.windowIcon().isNull():
            self._tray.setIcon(self.windowIcon())
        self._tray.setToolTip("turbobot")
        menu = QMenu(self)
        show_action = QAction("Открыть", self)
        show_action.triggered.connect(self.reveal)
        quit_action = QAction("Выход", self)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.messageClicked.connect(self._on_tray_message_clicked)
        self._tray.show()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.reveal()

    def _on_tool_request(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self.reveal()
        Thread(
            target=self.api._handle_sse_tool_request,
            kwargs={"payload": payload},
            daemon=True,
        ).start()

    def _on_tray_toast(self, title: str, body: str, workflow_id: str, run_id: str = "") -> None:
        self._last_toast_workflow_id = (workflow_id or "").strip()
        self._last_toast_run_id = (run_id or "").strip()
        self._tray.showMessage(title, body or "Открыть агента", QSystemTrayIcon.MessageIcon.Information, 10000)

    def _on_tray_message_clicked(self) -> None:
        if self._last_toast_workflow_id:
            self.open_workflow(self._last_toast_workflow_id, self._last_toast_run_id)
        else:
            self.reveal()

    def _try_restore_session(self) -> bool:
        stored = load_session()
        if stored is None:
            return False
        from app.chat.test_user import canonical_test_credentials, test_login_result

        if stored.access_token:
            self.api.set_token(stored.access_token)
            try:
                user = self.api.me()
            except ApiError:
                self.api.set_token(None)
            else:
                self._enter_main(user)
                return True
        creds = canonical_test_credentials(fio=stored.fio)
        if creds is not None:
            try:
                result = self.api.login(*creds)
            except ApiError:
                result = test_login_result(stored.fio)
                self.api.set_token(None)
                save_session(access_token="", fio=stored.fio)
            else:
                save_session(access_token=result.access_token, fio=result.user.fio)
            self._enter_main(result.user)
            return True
        clear_session(keep_fio=True)
        self.api.set_token(None)
        return False

    def _try_auto_login(self) -> bool:
        if auth_test_user():
            result = test_login_result()
            self._enter_main(result.user)
            return True
        fio = erp_login()
        password = erp_password()
        if not fio or not password:
            return False
        try:
            result = self.api.login(fio, password)
        except ApiError:
            return False
        save_session(access_token=result.access_token, fio=result.user.fio)
        self._enter_main(result.user)
        return True

    def _on_logged_in(self, result: LoginResult) -> None:
        self.login_page.fio_edit.hide_suggestions()
        self._enter_main(result.user)

    def _enter_main(self, user) -> None:
        configure_runtime_api(token=self.api.token, base_url=self.api.base_url)
        self.main_shell.set_user(user)
        self._stack.setCurrentWidget(self.main_shell)
        if self.api.token:
            self._notify.start(token=self.api.token, base_url=self.api.base_url)
        pending = self._pending_workflow_id
        pending_run = self._pending_run_id
        pending_live = self._pending_open_live
        pending_demo = self._pending_start_demo
        self._pending_workflow_id = ""
        self._pending_run_id = ""
        self._pending_open_live = False
        self._pending_start_demo = False
        self.main_shell.set_user(user, reset_home=not pending)
        if pending:
            if pending_demo:
                self.main_shell.navigate_to_agent_run(pending, start_demo=True)
            elif pending_live:
                self.main_shell.show_live_agent(pending)
            else:
                self.main_shell.navigate_to_agent_history(pending, pending_run)

    def _on_session_kicked(self, message: str) -> None:
        text = (message or "").strip() or "Выполнен вход на другом устройстве. Этот сеанс завершён."
        QMessageBox.information(self, "Сеанс завершён", text)
        self._on_logout()

    def _on_logout(self) -> None:
        current_fio = self._user.fio if getattr(self, "_user", None) is not None else "-"
        self._notify.stop()
        configure_runtime_api(token=None, base_url=self.api.base_url)
        self._terminate_creation_sessions()
        clear_session(keep_fio=True)
        self.api.set_token(None)
        if auth_skip_login_page() and self._try_auto_login():
            return
        self.login_page.reset_form()
        self._stack.setCurrentWidget(self.login_page)

    def quit_app(self) -> None:
        self._force_quit = True
        self._notify.stop()
        self._terminate_creation_sessions()
        QApplication.instance().quit()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._force_quit:
            self._notify.stop()
            self._terminate_creation_sessions()
            event.accept()
            return
        self._notify.stop()
        self._terminate_creation_sessions()
        event.accept()

    def _terminate_creation_sessions(self) -> None:
        try:
            self.api.terminate_regulation_creation_sessions()
        except ApiError:
            pass
