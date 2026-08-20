"""Один экземпляр десктопа: второй процесс передаёт команду и выходит."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

APP_KEY = "NewConstructor"


class SingleInstance(QObject):
    command_received = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        if not self._server.listen(APP_KEY):
            if not send_to_running("raise"):
                QLocalServer.removeServer(APP_KEY)
                self._server.listen(APP_KEY)

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
    socket = QLocalSocket()
    socket.connectToServer(APP_KEY)
    if not socket.waitForConnected(400):
        return False
    socket.write(command.encode("utf-8"))
    socket.waitForBytesWritten(400)
    socket.disconnectFromServer()
    return True
