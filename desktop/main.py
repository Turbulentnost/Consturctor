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

for _noisy_logger in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(_noisy_logger).setLevel(logging.WARNING)

from app.frozen_runtime import entry_mode, run_agent_python, run_com_worker

APP_ID = "NewConstructor"


def _configure_console_encoding() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="backslashreplace")
            except Exception:
                pass


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass


def _prepare_display() -> None:
    """Match Cursor: per-monitor DPI so Windows does not stretch a 96-DPI bitmap."""
    import os

    # pytest / Cursor leftover: offscreen makes the app "start" with no window.
    if os.environ.get("QT_QPA_PLATFORM", "").strip().lower() in {
        "offscreen",
        "minimal",
        "minimalegl",
    }:
        os.environ.pop("QT_QPA_PLATFORM", None)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # Same as Cursor.exe: SetProcessDpiAwarenessContext + dpiAware true/pm
        # -4 = DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        user32 = ctypes.windll.user32
        if hasattr(user32, "SetProcessDpiAwarenessContext"):
            user32.SetProcessDpiAwarenessContext.restype = ctypes.c_int
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
            if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _open_workflow_id(argv: list[str]) -> str:
    for index, item in enumerate(argv[1:], start=1):
        if item.startswith("--open-workflow="):
            return item.split("=", 1)[1].strip()
        if item == "--open-workflow" and index + 1 < len(argv):
            return argv[index + 1].strip()
    return ""


def _open_run_id(argv: list[str]) -> str:
    for index, item in enumerate(argv[1:], start=1):
        if item.startswith("--open-run="):
            return item.split("=", 1)[1].strip()
        if item == "--open-run" and index + 1 < len(argv):
            return argv[index + 1].strip()
    return ""


def _wants_background(argv: list[str]) -> bool:
    return "--background" in argv or "--hidden" in argv


def _wants_start_demo(argv: list[str]) -> bool:
    return "--start-demo" in argv


def _handoff_command(argv: list[str]) -> str:
    workflow_id = _open_workflow_id(argv)
    run_id = _open_run_id(argv)
    if workflow_id and _wants_start_demo(argv):
        return f"start-demo:{workflow_id}"
    if workflow_id and run_id:
        return f"open-workflow:{workflow_id}|{run_id}"
    if workflow_id:
        return f"open-workflow:{workflow_id}"
    return "raise"


def _ipc_command(argv: list[str]) -> str | None:
    for index, item in enumerate(argv[1:], start=1):
        if item.startswith("--ipc="):
            return item.split("=", 1)[1].strip() or _handoff_command(argv)
        if item == "--ipc":
            nxt = argv[index + 1] if index + 1 < len(argv) else ""
            if nxt and not nxt.startswith("-"):
                return nxt.strip()
            return _handoff_command(argv)
    return None


def _run_ipc(command: str) -> int:
    import time

    from app.single_instance import send_to_running

    if send_to_running(command):
        return 0
    for _ in range(20):
        time.sleep(0.05)
        if send_to_running(command):
            return 0
    return 1


def _run_gui() -> int:
    import time

    _prepare_display()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from app.config import bundle_path
    from app.single_instance import SingleInstance, send_to_running
    from app.ui.app_window import AppWindow
    from app.ui.theme import app_font, load_fonts, qss_global

    _set_app_user_model_id()
    workflow_id = _open_workflow_id(sys.argv)
    run_id = _open_run_id(sys.argv)
    start_demo = _wants_start_demo(sys.argv)
    background = _wants_background(sys.argv)
    command = "ping" if background else _handoff_command(sys.argv)
    if send_to_running(command):
        if not background:
            print("Уже запущен — поднимаю существующее окно.")
        return 0

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)
    app.setApplicationName("NewConstructor")
    if send_to_running(command):
        if not background:
            print("Уже запущен — поднимаю существующее окно.")
        return 0

    instance = SingleInstance(app)
    if not instance.is_listening:
        for _ in range(20):
            time.sleep(0.05)
            if send_to_running(command):
                return 0
        return 0

    logo = bundle_path("app", "ui", "temp", "logo.png")
    if not logo.exists():
        logo = ROOT / "app" / "ui" / "temp" / "logo.png"
    if logo.exists():
        app.setWindowIcon(QIcon(str(logo)))
    family = load_fonts()
    app.setFont(app_font(14, QFont.Weight.Normal))
    app.setStyleSheet(qss_global(family))

    window = AppWindow(
        open_workflow_id=workflow_id,
        open_run_id=run_id,
        start_demo=start_demo,
    )
    instance.command_received.connect(window.handle_external_command)
    if not background:
        window.show()
    return app.exec()


def main() -> int:
    _configure_console_encoding()
    _prepare_display()
    mode = entry_mode()
    if mode == "com-worker":
        return run_com_worker()
    if mode == "agent-python":
        return run_agent_python()
    ipc = _ipc_command(sys.argv)
    if ipc is not None:
        return _run_ipc(ipc)
    return _run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
