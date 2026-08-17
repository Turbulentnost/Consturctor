"""Фоновый WebSocket-клиент и Windows toast."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

import httpx
from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtWebSockets import QWebSocket

from app.config import backend_url

logger = logging.getLogger(__name__)

APP_ID = "NewConstructor"
_PS_AUMID = (
    r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
)


class NotificationService(QObject):
    open_workflow_requested = Signal(str)
    toast_requested = Signal(str, str, str)
    command_received = Signal(dict)

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
        self._ws.connected.connect(self._on_connected)
        self._ws.disconnected.connect(self._on_disconnected)
        self._ws.textMessageReceived.connect(self._on_message)
        self._ws.errorOccurred.connect(lambda *_: self._schedule_reconnect())

    def start(self, *, token: str, base_url: str = "") -> None:
        self._token = token
        self._base_url = (base_url or backend_url()).rstrip("/")
        self._connect()
        self._poll_pending()
        if not self._poll.isActive():
            self._poll.start()

    def stop(self) -> None:
        self._reconnect.stop()
        self._poll.stop()
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

    def _on_connected(self) -> None:
        logger.info("Notification websocket connected")
        self._poll_pending()

    def _on_disconnected(self) -> None:
        self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._token and not self._reconnect.isActive():
            self._reconnect.start()

    def _on_message(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        kind = str(payload.get("type") or "")
        if kind in {"evaluate_trigger", "run_agent"}:
            self.command_received.emit(payload)
            return
        if kind and kind != "notification":
            return
        self._present(payload)

    def _poll_pending(self) -> None:
        if not self._token:
            return
        try:
            response = httpx.get(
                f"{self._base_url}/api/v1/notifications/pending",
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=10.0,
            )
            if response.status_code >= 400:
                return
            items = response.json()
        except Exception:  # noqa: BLE001
            logger.debug("Pending notification poll failed", exc_info=True)
            return
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            shown = self._present(item)
            nid = str(item.get("id") or "")
            if shown and nid:
                self._ack(nid)

    def _ack(self, notification_id: str) -> None:
        try:
            httpx.post(
                f"{self._base_url}/api/v1/notifications/{notification_id}/ack",
                headers={"Authorization": f"Bearer {self._token}", "Accept": "application/json"},
                timeout=10.0,
            )
        except Exception:  # noqa: BLE001
            logger.debug("Notification ack failed id=%s", notification_id, exc_info=True)

    def _present(self, payload: dict) -> bool:
        nid = str(payload.get("id") or "")
        if nid and nid in self._seen:
            return False
        if nid:
            self._seen.add(nid)
        title = str(payload.get("title") or "Уведомление")
        body = str(payload.get("body") or "")
        workflow_id = str(payload.get("workflow_id") or "")
        if not show_windows_toast(title, body, workflow_id):
            self.toast_requested.emit(title, body, workflow_id)
        return True


def show_windows_toast(title: str, body: str, workflow_id: str = "") -> bool:
    launch = _launch_command(workflow_id)
    icon = _toast_icon()
    message = (body or "Открыть агента")[:240]
    heading = title[:120]
    for app_id in (_PS_AUMID, APP_ID):
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
            return True
        except Exception:  # noqa: BLE001
            logger.debug("winotify failed app_id=%s", app_id, exc_info=True)
    logger.warning("winotify unavailable, tray balloon will be used")
    return False


def _toast_icon() -> str:
    logo = Path(__file__).resolve().parents[1] / "ui" / "temp" / "logo.png"
    return str(logo) if logo.exists() else ""


def _launch_command(workflow_id: str) -> str:
    if not workflow_id:
        return ""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return f'"{exe}" --open-workflow={workflow_id}'
    main = Path(__file__).resolve().parents[2] / "main.py"
    return f'"{sys.executable}" "{main}" --open-workflow={workflow_id}'
