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
        if kind == "evaluate_trigger":
            self._start_check(payload)
            return
        if kind == "run_agent":
            self._start_run(payload)

    def _start_check(self, payload: dict) -> None:
        with self._lock:
            if self._check_busy:
                logger.info("Skip trigger check: already running")
                return
            self._check_busy = True
        Thread(target=self._check, args=(payload,), daemon=True).start()

    def _start_run(self, payload: dict) -> None:
        with self._lock:
            busy = self._run_busy
            if not busy:
                self._run_busy = True
        if busy:
            logger.info("Skip agent run: already running")
            self._cancel_overlap_slot(payload)
            return
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
        events: list[dict] = []
        run_id = ""
        try:
            if not workflow_id:
                return
            record = self._api.get_workflow(workflow_id)
            if not message:
                title = str(getattr(record, "title", "") or "")
                message = (
                    f"Выполни рабочую задачу агента «{title or 'агент'}» по правилам из его плана "
                    "и покажи понятный результат."
                )
            self._toast("Агент запущен по триггеру", message[:180], workflow_id)
            from app.sdk_agent import CursorSdkBridge, CursorSdkUnavailable
            from app.sdk_agent.files import prepare_sdk_workspace
            from app.sdk_agent.prompt import build_sdk_prompt

            bridge = CursorSdkBridge()
            try:
                bridge.check_ready()
            except CursorSdkUnavailable:
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
                return
            history = self._api.start_local_agent_run(
                workflow_id,
                message=message,
                source="trigger",
                trigger_id=trigger_id,
                evidence=str(payload.get("evidence") or ""),
            )
            run_id = history.id

            def collect(event: dict) -> None:
                if isinstance(event, dict) and event.get("type") not in {"ready", "done"}:
                    events.append(event)

            try:
                run_cwd = bridge.workspace_cwd(workflow_id)
                prepare_sdk_workspace(
                    self._api,
                    workflow_id,
                    run_cwd,
                    workflow=record,
                )
                result = bridge.run(
                    prompt=build_sdk_prompt(record, message),
                    workflow_id=workflow_id,
                    cwd=run_cwd,
                    on_event=collect,
                )
                answer = str(result.get("answer") or "")
                self._api.finish_local_agent_run(
                    workflow_id,
                    run_id,
                    status="ok",
                    answer=answer,
                    events=events,
                    message=message,
                )
            except CursorSdkUnavailable:
                self._api.finish_local_agent_run(
                    workflow_id,
                    run_id,
                    status="error",
                    answer="Cursor SDK стал недоступен во время запуска.",
                    events=events,
                    message=message,
                )
                raise
            except Exception as exc:  # noqa: BLE001
                self._api.finish_local_agent_run(
                    workflow_id,
                    run_id,
                    status="error",
                    answer=str(exc),
                    events=events,
                    message=message,
                )
                raise
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

    def _cancel_overlap_slot(self, payload: dict) -> None:
        workflow_id = str(payload.get("workflow_id") or "").strip()
        trigger_id = str(payload.get("trigger_id") or payload.get("id") or "").strip()
        if not workflow_id or not trigger_id:
            return
        try:
            self._api.cancel_overlapping_slot(
                workflow_id,
                trigger_id,
                answer="Агент уже выполняется",
            )
        except ApiError as exc:
            logger.warning("Overlap cancel failed: %s", exc)

    def _toast(self, title: str, body: str, workflow_id: str) -> None:
        if not show_windows_toast(title, body, workflow_id):
            self.toast_requested.emit(title, body, workflow_id)
