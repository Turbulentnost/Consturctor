"""Фоновый запуск опубликованного агента и проверка условий триггера."""

from __future__ import annotations

import logging
from threading import Lock, Thread

from PySide6.QtCore import QObject, Signal

from app.api_client import ApiClient, ApiError
from app.notifications.service import show_windows_toast

logger = logging.getLogger(__name__)


class HeadlessRunner(QObject):
    toast_requested = Signal(str, str, str)

    def __init__(self, api: ApiClient, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._api = api
        self._lock = Lock()
        self._check_busy = False
        self._run_busy = False

    def handle_command(self, payload: dict) -> None:
        kind = str(payload.get("type") or "")
        if kind in {"evaluate_trigger", "run_agent"}:
            logger.info("Skip %s: scheduled runs are owned by the server worker", kind)

    def _start_check(self, payload: dict) -> None:
        with self._lock:
            if self._check_busy:
                logger.info("Skip trigger check: already running")
                return
            self._check_busy = True
        Thread(target=self._check, args=(payload,), daemon=True).start()

    def _start_run(self, payload: dict) -> None:
        with self._lock:
            if self._run_busy:
                logger.info("Skip agent run: already running")
                return
            self._run_busy = True
        Thread(target=self._run, args=(payload,), daemon=True).start()

    def _check(self, payload: dict) -> None:
        trigger_id = str(payload.get("trigger_id") or payload.get("id") or "")
        try:
            if not trigger_id:
                return
            result = self._api.stream_trigger_check(trigger_id)
            matched = bool(result.get("matched"))
            evidence = str(result.get("changed") or result.get("evidence") or "")
            if not matched:
                logger.info("Trigger %s not matched: %s", trigger_id, evidence[:200])
                return
            self._api.ack_trigger_fired(trigger_id, evidence=evidence)
            self._start_run(
                {
                    "type": "run_agent",
                    "workflow_id": payload.get("workflow_id") or "",
                    "message": payload.get("message") or "",
                    "trigger_id": trigger_id,
                    "title": payload.get("title") or "",
                    "acked": True,
                    "evidence": evidence,
                    "condition_text": payload.get("condition_text") or payload.get("condition") or "",
                }
            )
        except ApiError as exc:
            logger.warning("Trigger check failed id=%s: %s", trigger_id, exc)
        except Exception:  # noqa: BLE001
            logger.exception("Trigger check crashed id=%s", trigger_id)
        finally:
            with self._lock:
                self._check_busy = False

    def _run(self, payload: dict) -> None:
        workflow_id = str(payload.get("workflow_id") or "").strip()
        trigger_id = str(payload.get("trigger_id") or payload.get("id") or "")
        message = str(payload.get("message") or "").strip()
        try:
            if not workflow_id:
                return
            if not message:
                title = ""
                try:
                    record = self._api.get_workflow(workflow_id)
                    title = str(getattr(record, "title", "") or "")
                except ApiError:
                    title = ""
                message = (
                    f"Выполни рабочую задачу агента «{title or 'агент'}» по правилам из его плана "
                    "и покажи понятный результат."
                )
            self._toast("Агент запущен по триггеру", message[:180], workflow_id)
            self._api.stream_workflow_agent_run(
                workflow_id,
                message,
                lambda _payload: None,
                source="trigger",
                trigger_id=trigger_id,
                evidence=str(payload.get("evidence") or ""),
            )
            if trigger_id and not payload.get("acked"):
                self._api.ack_trigger_fired(trigger_id, evidence=str(payload.get("evidence") or "запущен"))
            self._toast("Агент завершил работу", "Нажмите, чтобы открыть ход", workflow_id)
        except ApiError as exc:
            logger.warning("Headless agent run failed workflow=%s: %s", workflow_id, exc)
            self._toast("Агент не запустился", str(exc)[:180], workflow_id)
        except Exception:  # noqa: BLE001
            logger.exception("Headless agent run crashed workflow=%s", workflow_id)
        finally:
            with self._lock:
                self._run_busy = False

    def _toast(self, title: str, body: str, workflow_id: str) -> None:
        if not show_windows_toast(title, body, workflow_id):
            self.toast_requested.emit(title, body, workflow_id)
