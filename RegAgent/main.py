from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and str(meipass) not in sys.path:
        sys.path.insert(0, str(meipass))
elif str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    from app.subprocess_win import apply_global_subprocess_patch

    apply_global_subprocess_patch()

from app.config import ensure_data_dirs


def main() -> int:
    from app.frozen_runtime import entry_mode, run_agent_python, run_com_worker

    mode = entry_mode()
    if mode == "com-worker":
        return run_com_worker()
    if mode == "agent-python":
        return run_agent_python()

    logging.basicConfig(level=logging.INFO)
    ensure_data_dirs()

    from app.cursor_sdk_win_patch import prewarm_bridge

    threading.Thread(
        target=prewarm_bridge,
        name="cursor-bridge-prewarm",
        daemon=True,
    ).start()

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
