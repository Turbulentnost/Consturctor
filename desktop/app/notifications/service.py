"""Фоновый WebSocket-клиент и Windows toast."""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket

from app.config import backend_url

logger = logging.getLogger(__name__)

APP_ID = "NewConstructor"
_PS_AUMID = (
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
)


def latest_pending_payloads(items: list[object]) -> tuple[list[dict], dict | None]:
    """From a pending backlog, keep only the newest toast payload."""
    rows = [item for item in items if isinstance(item, dict)]
    if not rows:
        return [], None
    return rows[:-1], rows[-1]


def classify_ws_payload(payload: dict) -> str:
    kind = str(payload.get("type") or "")
    if kind == "session_replaced":
        return "kick"
    if kind in {"evaluate_trigger", "run_agent"}:
        return "command"
    if kind == "board_updated":
        return "board"
    if kind == "tool_request":
        return "tool"
    if kind in {"chat_message", "chat_receipt", "presence", "ticket_updated", "thread_opened"}:
        return "chat"
    if kind and kind != "notification":
        return "ignore"
    return "notification"


class NotificationService(QObject):
    open_workflow_requested = Signal(str)
    toast_requested = Signal(str, str, str, str)
    command_received = Signal(dict)
    inbox_changed = Signal()
    session_kicked = Signal(str)
    board_updated = Signal(dict)
    tool_requested = Signal(dict)
    chat_event = Signal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._ws = QWebSocket()
        self._token = ""
        self._base_url = backend_url()
        self._seen: set[str] = set()
        self._reconnect = QTimer(self)
        self._reconnect.setInterval(4000)
        self._reconnect.setSingleShot(True)
        self._reconnect.timeout.connect(self._connect)
        self._poll = QTimer(self)
        self._poll.setInterval(15000)
        self._poll.timeout.connect(self._poll_pending)
        self._ping = QTimer(self)
        self._ping.setInterval(20000)
        self._ping.timeout.connect(self._send_ping)
        self._kicked = False
        self._queued_toast: dict | None = None
        self._toast_batch = QTimer(self)
        self._toast_batch.setInterval(600)
        self._toast_batch.setSingleShot(True)
        self._toast_batch.timeout.connect(self._flush_toast_batch)
        self._ws.connected.connect(self._on_connected)
        self._ws.disconnected.connect(self._on_disconnected)
        self._ws.textMessageReceived.connect(self._on_message)
        self._ws.errorOccurred.connect(lambda *_: self._schedule_reconnect())

    def start(self, *, token: str, base_url: str = "") -> None:
        self._token = token
        self._base_url = (base_url or backend_url()).rstrip("/")
        self._kicked = False
        self._connect()
        self._poll_pending()
        if not self._poll.isActive():
            self._poll.start()
        if not self._ping.isActive():
            self._ping.start()

    def stop(self) -> None:
        self._reconnect.stop()
        self._poll.stop()
        self._ping.stop()
        self._token = ""
        self._ws.close()

    def _connect(self) -> None:
        if not self._token:
            return
        parsed = urlparse(self._base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        host = parsed.netloc or "127.0.0.1:7812"
        url = f"{scheme}://{host}/api/v1/notifications/ws?token={quote(self._token)}"
        self._ws.open(QUrl(url))

    def _send_ping(self) -> None:
        if self._token and self._ws.state() == QAbstractSocket.SocketState.ConnectedState:
            self._ws.sendTextMessage("ping")

    def _on_connected(self) -> None:
        logger.info("Notification websocket connected")
        self._poll_pending()

    def _on_disconnected(self) -> None:
        code = 0
        try:
            raw = self._ws.closeCode()
            code = int(getattr(raw, "value", raw) or 0)
        except (TypeError, ValueError):
            code = 0
        if self._kicked or code == 4001:
            return
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._kicked or not self._token:
            return
        if not self._reconnect.isActive():
            self._reconnect.start()

    def _on_message(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        kind = classify_ws_payload(payload)
        if kind == "kick":
            self._kick(str(payload.get("message") or "Сеанс завершён на другом устройстве."))
            return
        if kind == "command":
            self.command_received.emit(payload)
            return
        if kind == "board":
            self.board_updated.emit(payload)
            return
        if kind == "tool":
            self.tool_requested.emit(payload)
            return
        if kind == "chat":
            self.chat_event.emit(payload)
            return
        if kind != "notification":
            return
        self._queue_toast(payload)

    def _poll_pending(self) -> None:
        if not self._token:
            return
        try:
            response = httpx.get(
                f"{self._base_url}/api/v1/notifications/pending",
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=10.0,
            )
            if response.status_code == 401:
                self._kick("Сеанс завершён на другом устройстве.")
                return
            if response.status_code >= 400:
                return
            items = response.json()
        except Exception:  # noqa: BLE001
            logger.debug("Pending notification poll failed", exc_info=True)
            return
        if not isinstance(items, list):
            return
        older, latest = latest_pending_payloads(items)
        for item in older:
            nid = str(item.get("id") or "")
            if nid:
                self._seen.add(nid)
                self._ack(nid)
        if latest is None:
            return
        shown = self._present(latest)
        nid = str(latest.get("id") or "")
        if shown and nid:
            self._ack(nid)

    def _kick(self, message: str) -> None:
        if self._kicked:
            return
        self._kicked = True
        self.stop()
        self.session_kicked.emit(message or "Сеанс завершён на другом устройстве.")

    def _ack(self, notification_id: str) -> None:
        try:
            httpx.post(
                f"{self._base_url}/api/v1/notifications/{notification_id}/ack",
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=10.0,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Notification ack failed id=%s", notification_id, exc_info=True)

    def _queue_toast(self, payload: dict) -> None:
        nid = str(payload.get("id") or "")
        if nid and nid in self._seen:
            return
        if nid:
            self._seen.add(nid)
        self._queued_toast = payload
        if not self._toast_batch.isActive():
            self._toast_batch.start()

    def _flush_toast_batch(self) -> None:
        payload = self._queued_toast
        self._queued_toast = None
        if payload is None:
            return
        self._present(payload)

    def _present(self, payload: dict) -> bool:
        nid = str(payload.get("id") or "")
        if nid:
            self._seen.add(nid)
        title = str(payload.get("title") or "Уведомление")
        body = str(payload.get("body") or "")
        workflow_id = str(payload.get("workflow_id") or "")
        run_id = str(payload.get("run_id") or "")
        if not show_windows_toast(title, body, workflow_id, run_id):
            self.toast_requested.emit(title, body, workflow_id, run_id)
        self.inbox_changed.emit()
        return True


def show_windows_toast(
    title: str,
    body: str,
    workflow_id: str = "",
    run_id: str = "",
    *,
    from_foreground: bool = False,
) -> bool:
    launch = _launch_command(workflow_id, run_id)
    icon = _toast_icon()
    message = _toast_text(body or "Открыть агента", 240)
    heading = _toast_text(title, 120)
    # PowerShell AUMID — Windows не глотает тост, даже если наше окно на переднем плане.
    app_ids = [_PS_AUMID] if from_foreground else (_PS_AUMID, APP_ID)
    for app_id in app_ids:
        try:
            from winotify import Notification

            toast = Notification(
                app_id=app_id,
                title=heading,
                msg=message,
                icon=icon,
                duration="long",
                launch=launch,
            )
            if launch:
                toast.add_actions(label="Открыть", launch=launch)
            toast.show()
            logger.info("Windows toast shown title=%s app_id=%s", heading, app_id)
            return True
        except Exception:  # noqa: BLE001
            logger.warning("winotify failed app_id=%s", app_id, exc_info=True)
    logger.warning("winotify unavailable, tray balloon will be used")
    return False


def _toast_text(value: str, limit: int) -> str:
    text = (value or "").replace("]]>", " ").replace('"', "'").replace("`", "").replace("$", "")
    return text[:limit]


def _toast_icon() -> str:
    logo = Path(__file__).resolve().parents[1] / "ui" / "temp" / "logo.png"
    if not logo.exists():
        return ""
    return logo.resolve().as_uri()


def _launch_command(workflow_id: str, run_id: str = "") -> str:
    """URI для клика по тосту. Не командная строка: кавычки ломают XML winotify."""
    if not workflow_id:
        return ""
    folder = Path(tempfile.gettempdir()) / "constructor-toasts"
    folder.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch for ch in workflow_id if ch.isalnum())[:32] or "agent"
    script = folder / f"open-{safe}.py"
    cmd_path = folder / f"open-{safe}.cmd"
    exe = Path(sys.executable).resolve()
    rid = (run_id or "").strip()
    if getattr(sys, "frozen", False):
        payload = (
            "import subprocess\n"
            f"exe = {str(exe)!r}\n"
            f"wid = {workflow_id!r}\n"
            f"rid = {rid!r}\n"
            "args = [exe, f'--open-workflow={wid}']\n"
            "if rid:\n"
            "    args.append(f'--open-run={rid}')\n"
            "subprocess.Popen(args, close_fds=True)\n"
        )
    else:
        main = Path(__file__).resolve().parents[2] / "main.py"
        payload = (
            "import subprocess\n"
            f"exe = {str(exe)!r}\n"
            f"main = {str(main)!r}\n"
            f"wid = {workflow_id!r}\n"
            f"rid = {rid!r}\n"
            "args = [exe, main, f'--open-workflow={wid}']\n"
            "if rid:\n"
            "    args.append(f'--open-run={rid}')\n"
            "subprocess.Popen(args, close_fds=True)\n"
        )
    script.write_text(payload, encoding="utf-8")
    line = f'@echo off\r\n"{exe}" "{script}"\r\n'
    try:
        cmd_path.write_text(line, encoding="ascii")
    except UnicodeEncodeError:
        cmd_path.write_text(line, encoding="utf-8-sig")
    return cmd_path.resolve().as_uri()
