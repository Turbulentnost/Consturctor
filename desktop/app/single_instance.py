"""Один экземпляр десктопа: второй процесс передаёт команду и выходит."""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from app.config import constructor_instance
from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def app_key() -> str:
    inst = constructor_instance()
    return f"NewConstructor.{inst}" if inst else "NewConstructor"


APP_KEY = app_key()


def lock_path() -> Path:
    return Path(tempfile.gettempdir()) / f"{app_key()}.lock"


class SingleInstance(QObject):
    command_received = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = QLockFile(str(lock_path()))
        self._lock.setStaleLockTime(30_000)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        if not self._lock.tryLock(200):
            return
        if not self._server.listen(app_key()):
            QLocalServer.removeServer(app_key())
            self._server.listen(app_key())

    @property
    def is_listening(self) -> bool:
        return self._server.isListening()

    def _on_connection(self) -> None:
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        socket.readyRead.connect(lambda sock=socket: self._read(sock))

    def _read(self, socket: QLocalSocket) -> None:
        raw = bytes(socket.readAll()).decode("utf-8", errors="replace").strip()
        socket.close()
        if raw:
            self.command_received.emit(raw)


def send_to_running(command: str) -> bool:
    if _send_qt(command):
        return True
    return _send_win32(command)


def _send_qt(command: str) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(app_key())
    if not socket.waitForConnected(400):
        return False
    socket.write(command.encode("utf-8"))
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True


def _send_win32(command: str, timeout_ms: int = 400) -> bool:
    if sys.platform != "win32":
        return False
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    generic_rw = 0xC0000000
    open_existing = 3
    error_pipe_busy = 231
    pipe = f"\\\\.\\pipe\\{app_key()}"
    invalid = ctypes.c_void_p(-1).value
    deadline = time.monotonic() + timeout_ms / 1000.0
    handle = invalid
    while time.monotonic() < deadline:
        handle = kernel32.CreateFileW(pipe, generic_rw, 0, None, open_existing, 0, None)
        if handle not in {invalid, 0, -1}:
            break
        if ctypes.get_last_error() == error_pipe_busy:
            kernel32.WaitNamedPipeW(pipe, 50)
            continue
        time.sleep(0.02)
        handle = invalid
    if handle in {invalid, 0, -1}:
        return False
    try:
        payload = command.encode("utf-8")
        written = wintypes.DWORD()
        ok = kernel32.WriteFile(handle, payload, len(payload), ctypes.byref(written), None)
        return bool(ok)
    finally:
        kernel32.CloseHandle(handle)
