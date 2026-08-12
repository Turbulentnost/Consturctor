from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow

from app.ui.main_shell import MainShell
from app.ui.theme import WINDOW_HEIGHT, WINDOW_WIDTH


class AppWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Cursor Constructor")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)
        self.setMinimumSize(1024, 700)
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
        )
        self.setCentralWidget(MainShell())

    def closeEvent(self, event) -> None:  # noqa: N802
        # Background QThreads (network streaming) may still be alive on close.
        # Tearing them down via Qt's normal shutdown can abort with 0xC0000409
        # on Windows. Exit the process immediately with a clean code instead.
        event.accept()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
