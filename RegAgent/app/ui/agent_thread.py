from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot

from app.agent.runtime import AgentRunCancelled, CardAgentSession, RuntimeAgentError
from app.models import Card
from app.tools.bridge import set_confirm_callback
from app.tools.confirm_bridge import confirm_from_worker, reject_pending_confirm


class AgentWorker(QObject):
    """Все вызовы Cursor SDK — только в этом потоке."""

    opened = Signal(str, str)  # card_id, agent_id
    open_failed = Signal(str)
    event = Signal(object)
    finished = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._session: CardAgentSession | None = None
        self._cancel_event = threading.Event()

    def request_cancel(self) -> None:
        self._cancel_event.set()
        reject_pending_confirm()
        if self._session is not None:
            self._session.cancel_current_run()

    @Slot(object)
    def open_card(self, card: object) -> None:
        if not isinstance(card, Card):
            self.open_failed.emit("Некорректная карточка")
            return
        self._close_quiet()
        set_confirm_callback(confirm_from_worker)
        try:
            session = CardAgentSession(card)
            session.open()
            self._session = session
            self.opened.emit(card.id, session.agent_id)
            self.event.emit({"type": "status", "text": "Агент готов"})
        except Exception as exc:
            set_confirm_callback(None)
            self.open_failed.emit(str(exc))

    @Slot(str, bool, list)
    def send(self, text: str, action: bool, attachments: list) -> None:
        self._cancel_event.clear()
        paths = [str(item) for item in attachments if str(item).strip()]
        try:
            if self._session is None:
                raise RuntimeAgentError("Агент не подключён")
            cancel_check = self._cancel_event.is_set
            if action:
                answer = self._session.send_action(
                    text,
                    on_event=self._emit,
                    attachment_paths=paths or None,
                    cancel_check=cancel_check,
                )
            else:
                answer = self._session.send(
                    text,
                    on_event=self._emit,
                    attachment_paths=paths or None,
                    cancel_check=cancel_check,
                )
            self.finished.emit({"ok": True, "text": answer})
        except AgentRunCancelled as exc:
            self.finished.emit({"ok": False, "error": str(exc), "cancelled": True})
        except Exception as exc:
            cancelled = self._cancel_event.is_set()
            self.finished.emit({"ok": False, "error": str(exc), "cancelled": cancelled})
        finally:
            self._cancel_event.clear()

    @Slot()
    def close_agent(self) -> None:
        self._close_quiet()
        set_confirm_callback(None)

    def _close_quiet(self) -> None:
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

    def _emit(self, event: dict) -> None:
        self.event.emit(event)


class AgentThreadController(QObject):
    """UI-side handle: запросы в worker через QueuedConnection."""

    opened = Signal(str, str)
    open_failed = Signal(str)
    event = Signal(object)
    finished = Signal(object)

    _request_open = Signal(object)
    _request_send = Signal(str, bool, list)
    _request_close = Signal()
    _request_cancel = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread = QThread()
        self._worker = AgentWorker()
        self._worker.moveToThread(self._thread)

        self._worker.opened.connect(self.opened.emit)
        self._worker.open_failed.connect(self.open_failed.emit)
        self._worker.event.connect(self.event.emit)
        self._worker.finished.connect(self.finished.emit)

        self._request_open.connect(self._worker.open_card, Qt.ConnectionType.QueuedConnection)
        self._request_send.connect(self._worker.send, Qt.ConnectionType.QueuedConnection)
        self._request_close.connect(self._worker.close_agent, Qt.ConnectionType.QueuedConnection)
        self._request_cancel.connect(self._worker.request_cancel, Qt.ConnectionType.QueuedConnection)

        self._thread.start()

    def open_card(self, card: Card) -> None:
        self._request_open.emit(card)

    def send(
        self,
        text: str,
        *,
        action: bool = False,
        attachments: list[str] | None = None,
    ) -> None:
        self._request_send.emit(text, action, list(attachments or []))

    def cancel(self) -> None:
        self._request_cancel.emit()

    def shutdown(self) -> None:
        self._request_close.emit()
        self._thread.quit()
        self._thread.wait(8000)
