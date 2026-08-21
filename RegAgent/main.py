from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import ensure_data_dirs


def main() -> int:
    from app.frozen_runtime import entry_mode, run_com_worker

    mode = entry_mode()
    if mode == "com-worker":
        return run_com_worker()

    logging.basicConfig(level=logging.INFO)
    ensure_data_dirs()

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from app.ui.app_window import AppWindow
    from app.ui.theme import app_font, load_fonts, qss_global

    app = QApplication(sys.argv)
    family = load_fonts()
    app.setFont(app_font(14))
    app.setStyleSheet(qss_global(family))
    window = AppWindow()
    window.show()
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
