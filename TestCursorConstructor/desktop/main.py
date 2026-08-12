from __future__ import annotations

import datetime
import faulthandler
import os
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ловим падения. Без этого исключение в Qt-слоте на новых PySide6 завершает
# процесс с кодом 0xC0000409 без видимого трейсбека.
# Нативные сбои (access violation) пишем в отдельный файл с полным стеком.
_FAULT_LOG_PATH = ROOT / "data" / "faulthandler.log"
try:
    _FAULT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _FAULT_LOG = open(_FAULT_LOG_PATH, "a", encoding="utf-8", buffering=1)
    _FAULT_LOG.write(f"\n=== start {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
    _FAULT_LOG.flush()
    faulthandler.enable(file=_FAULT_LOG, all_threads=True)
except Exception:  # noqa: BLE001
    faulthandler.enable()


def _install_excepthook() -> None:
    log_path = ROOT / "data" / "crash.log"

    def hook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        sys.stderr.write(msg)
        sys.stderr.flush()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(f"\n=== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n{msg}")
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


_install_excepthook()

from PySide6.QtWidgets import QApplication

from app.ui.app_window import AppWindow
from app.ui.theme import load_fonts, qss_global


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Cursor Constructor")
    family = load_fonts()
    app.setStyleSheet(qss_global(family))

    window = AppWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    exit_code = main()
    # PySide6 on Windows can raise 0xC0000409 during interpreter/Qt teardown on
    # window close. os._exit bypasses that shutdown path and returns a clean code.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exit_code)
