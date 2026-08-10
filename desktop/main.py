from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from app.ui.app_window import AppWindow
from app.ui.theme import load_fonts, qss_global


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("turbobot")
    logo = ROOT / "app" / "ui" / "temp" / "logo.png"
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))
    family = load_fonts()
    app.setStyleSheet(qss_global(family))

    window = AppWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
