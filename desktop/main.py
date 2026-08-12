from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from app.host_manager import ensure_desktop_host, ensure_desktop_launcher
from app.ui.app_window import AppWindow
from app.ui.theme import app_font, load_fonts, qss_global


def main() -> int:
    # Round scale factors so text stays on the pixel grid (reduces blur at 125%/150%).
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
    )
    app = QApplication(sys.argv)
    app.setApplicationName("turbobot")
    logo = ROOT / "app" / "ui" / "temp" / "logo.png"
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))
    family = load_fonts()
    app.setFont(app_font(14, QFont.Weight.Normal))
    app.setStyleSheet(qss_global(family))

    ensure_desktop_host()
    ensure_desktop_launcher()

    window = AppWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
