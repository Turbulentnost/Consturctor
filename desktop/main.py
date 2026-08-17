from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass and str(meipass) not in sys.path:
        sys.path.insert(0, str(meipass))
elif str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from app.config import bundle_path
from app.single_instance import SingleInstance, send_to_running
from app.ui.app_window import AppWindow
from app.ui.theme import app_font, load_fonts, qss_global

APP_ID = "NewConstructor"


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _open_workflow_id(argv: list[str]) -> str:
    for index, item in enumerate(argv[1:], start=1):
        if item.startswith("--open-workflow="):
            return item.split("=", 1)[1].strip()
        if item == "--open-workflow" and index + 1 < len(argv):
            return argv[index + 1].strip()
    return ""


def _wants_background(argv: list[str]) -> bool:
    return "--background" in argv or "--hidden" in argv


def main() -> int:
    _set_app_user_model_id()
    workflow_id = _open_workflow_id(sys.argv)
    background = _wants_background(sys.argv)
    command = f"open-workflow:{workflow_id}" if workflow_id else "raise"
    if not background and send_to_running(command):
        return 0
    if background and send_to_running("ping"):
        return 0

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("NewConstructor")
    logo = bundle_path("app", "ui", "temp", "logo.png")
    if not logo.exists():
        logo = ROOT / "app" / "ui" / "temp" / "logo.png"
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))
    family = load_fonts()
    app.setFont(app_font(14, QFont.Weight.Normal))
    app.setStyleSheet(qss_global(family))

    window = AppWindow(open_workflow_id=workflow_id)
    instance = SingleInstance(app)
    instance.command_received.connect(window.handle_external_command)
    if not background:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
