"""Один экземпляр UI-приложения до старта Qt (Windows mutex + QLocalSocket)."""

from __future__ import annotations

import sys
import time

from PySide6.QtNetwork import QLocalSocket

APP_KEY = "NewConstructor"
_MUTEX_NAME = "Local\\NewConstructor.PrimaryInstance"


def try_become_primary() -> bool:
    """True — этот процесс главный; False — уже запущен другой экземпляр UI."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            return True
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            kernel32.CloseHandle(handle)
            return False
        return True
    except Exception:
        return True


def notify_running_instance(command: str, *, retries: int = 8) -> bool:
    for attempt in range(retries):
        socket = QLocalSocket()
        socket.connectToServer(APP_KEY)
        if socket.waitForConnected(500):
            socket.write(command.encode("utf-8"))
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return True
        if attempt + 1 < retries:
            time.sleep(0.25)
    return False


def warn_start_blocked() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "ConstructorDesktop уже запущен — проверьте панель задач (Alt+Tab).\n\n"
            "Если окна нет, запустите restart_app.bat из папки:\n"
            "dist\\ConstructorDesktop",
            "ConstructorDesktop",
            0x30,
        )
    except Exception:
        pass
