from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from app.api_client import ApiClient, ApiError, LoginResult
from app.config import (
    auth_skip_login_page,
    erp_login,
    erp_password,
    regagent_test_fio,
    regagent_test_login_enabled,
    regagent_test_password,
)
from app.session_store import clear_session, load_session
from app.ui.login_page import LoginPage
from app.ui.main_shell import MainShell
from app.ui.theme import WINDOW_HEIGHT, WINDOW_WIDTH

_log = logging.getLogger(__name__)


class AppWindow(QMainWindow):
    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()
        self.setObjectName("MainWindow")
        self.api = api or ApiClient()
        self.main_shell: MainShell | None = None
        self.setWindowTitle("RegAgent")
        logo = Path(__file__).resolve().parent / "temp" / "logo.png"
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(1024, 700)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self.login_page = LoginPage(self.api)
        self.login_page.logged_in.connect(self._on_logged_in)
        self._stack.addWidget(self.login_page)
        self._stack.setCurrentWidget(self.login_page)

        try:
            if auth_skip_login_page():
                if self._try_auto_login():
                    return
            else:
                self._try_restore_session()
        except Exception:
            _log.exception("Startup auth failed")
            clear_session(keep_fio=True)
            self.login_page.reset_form()
            self._stack.setCurrentWidget(self.login_page)

    def _ensure_main_shell(self) -> MainShell:
        if self.main_shell is None:
            self.main_shell = MainShell(self.api)
            self.main_shell.logout_requested.connect(self._on_logout)
            if auth_skip_login_page():
                self.main_shell.set_logout_visible(False)
            self._stack.addWidget(self.main_shell)
        return self.main_shell

    def _auto_login_credentials(self) -> tuple[str, str]:
        if regagent_test_login_enabled():
            fio = regagent_test_fio()
            password = regagent_test_password()
            if fio and password:
                return fio, password
        return erp_login(), erp_password()

    def _try_auto_login(self) -> bool:
        fio, password = self._auto_login_credentials()
        if not fio or not password:
            return False
        try:
            result = self.api.login(fio, password)
        except ApiError as exc:
            _log.info("Auto-login failed: %s", exc.message)
            return False
        except Exception:
            _log.exception("Auto-login failed")
            return False
        try:
            self._enter_main(result)
        except Exception:
            _log.exception("Failed to open main shell after auto-login")
            self.api.set_token(None)
            return False
        return True

    def _try_restore_session(self) -> bool:
        stored = load_session()
        if stored is None:
            return False
        self.api.set_token(stored.access_token)
        try:
            user = self.api.me()
        except ApiError as exc:
            _log.info("Session restore failed: %s", exc.message)
            clear_session(keep_fio=True)
            self.login_page.reset_form()
            return False
        try:
            self._enter_main(LoginResult(access_token=stored.access_token, user=user))
        except Exception:
            _log.exception("Failed to open main shell after session restore")
            self.api.set_token(None)
            clear_session(keep_fio=True)
            self.login_page.reset_form()
            return False
        return True

    def _on_logged_in(self, result: object) -> None:
        if not isinstance(result, LoginResult):
            return
        try:
            self._enter_main(result)
        except Exception:
            _log.exception("Failed to open main shell after login")
            self.api.set_token(None)
            clear_session(keep_fio=True)
            self.login_page.reset_form()
            self._stack.setCurrentWidget(self.login_page)

    def _enter_main(self, result: LoginResult) -> None:
        self.api.set_token(result.access_token)
        try:
            shell = self._ensure_main_shell()
            shell.set_user(result.user)
            self._stack.setCurrentWidget(shell)
        except Exception:
            self.api.set_token(None)
            raise

    def _on_logout(self) -> None:
        self.api.set_token(None)
        clear_session(keep_fio=True)
        self.login_page.reset_form()
        if auth_skip_login_page() and self._try_auto_login():
            return
        self._stack.setCurrentWidget(self.login_page)
