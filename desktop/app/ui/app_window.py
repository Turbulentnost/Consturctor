from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QStackedWidget

from app.api_client import ApiClient, LoginResult
from app.ui.login_page import LoginPage
from app.ui.main_shell import MainShell
from app.ui.theme import WINDOW_HEIGHT, WINDOW_WIDTH


class AppWindow(QMainWindow):
    def __init__(self, api: ApiClient | None = None) -> None:
        super().__init__()
        self.api = api or ApiClient()
        self.setWindowTitle("turbobot")
        logo = Path(__file__).resolve().parent / "temp" / "logo.png"
        if logo.exists():
            self.setWindowIcon(QIcon(str(logo)))
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
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

        self._stack.setCurrentWidget(self.login_page)

    def _on_logged_in(self, result: LoginResult) -> None:
        self.main_shell.set_user(result.user)
        self._stack.setCurrentWidget(self.main_shell)

    def _on_logout(self) -> None:
        self.api.set_token(None)
        self.login_page.reset_form()
        self._stack.setCurrentWidget(self.login_page)
