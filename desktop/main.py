from __future__ import annotations

import logging
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

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("desktop.main")

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


def _run_worker_mode() -> int | None:
    if "--desktop-host" in sys.argv:
        from platform_desktop_host.main import main as host_main

        host_main()
        return 0
    if "--desktop-launcher" in sys.argv:
        from platform_desktop_launcher.main import main as launcher_main

        launcher_main()
        return 0
    return None


def main() -> int:
    worker_exit = _run_worker_mode()
    if worker_exit is not None:
        return worker_exit

    from app.primary_instance import notify_running_instance, try_become_primary, warn_start_blocked
    from app.service_spawn import is_worker_argv

    workflow_id = _open_workflow_id(sys.argv)
    background = _wants_background(sys.argv)
    command = f"open-workflow:{workflow_id}" if workflow_id else "raise"

    if not is_worker_argv() and not try_become_primary():
        if notify_running_instance(command if not background else "ping"):
            return 0
        warn_start_blocked()
        logger.warning("Приложение уже запущено, но команда не передана — выхожу.")
        return 1

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from app.config import bundle_path
    from app.host_manager import ensure_desktop_host_async
    from app.single_instance import SingleInstance
    from app.ui.app_window import AppWindow
    from app.ui.theme import app_font, load_fonts, qss_global

    _set_app_user_model_id()

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

    instance = SingleInstance(app)
    window = AppWindow(open_workflow_id=workflow_id)
    instance.command_received.connect(window.handle_external_command)

    ensure_desktop_host_async()
    # Launcher (:7829) нужен orchestrator'у в Docker — не поднимаем его из UI,
    # чтобы не плодить лишние процессы. Host (:7830) достаточен для Excel/COM/Outlook.

    if not background:
        window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
