from __future__ import annotations

import sys
from pathlib import Path

# Allow `python main.py` from desktop/
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from app.api_client import ApiClient, LoginResult
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow


class AppController:
    def __init__(self) -> None:
        self.api = ApiClient()
        self.login_window = LoginWindow(self.api)
        self.main_window: MainWindow | None = None
        self.login_window.logged_in.connect(self._on_logged_in)

    def start(self) -> None:
        self.login_window.show()

    def _on_logged_in(self, result: LoginResult) -> None:
        self.login_window.hide()
        self.main_window = MainWindow(self.api, result.user)
        self.main_window.logout_btn.clicked.connect(self._on_logout)
        self.main_window.show()

    def _on_logout(self) -> None:
        self.api.set_token(None)
        if self.main_window is not None:
            self.main_window.close()
            self.main_window = None
        self.login_window.password_edit.clear()
        self.login_window.error_label.setText("")
        self.login_window.show()
        self.login_window.raise_()
        self.login_window.activateWindow()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Constructor")
    controller = AppController()
    controller.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
