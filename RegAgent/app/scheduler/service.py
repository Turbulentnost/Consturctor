"""Фоновый планировщик: запуск агентов по расписанию."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from PySide6.QtCore import QObject, QTimer, Signal

from app.agent.runtime import CardAgentSession
from app.models import Card, ScheduledTask
from app.scheduler.logic import format_iso, is_task_due
from app.storage.repository import CardRepository
from app.storage.scheduled_repository import ScheduledTaskRepository
from app.storage.session_log import load_session_log, save_session_log
from app.tools.bridge import set_confirm_callback
from app.tools.confirm_bridge import confirm_from_worker, reject_pending_confirm
from app.ui.agent_thread import AgentThreadController

_log = logging.getLogger(__name__)


class TaskSchedulerService(QObject):
    """Проверяет due-задачи каждую минуту и запускает агентов в фоне."""

    task_started = Signal(str, str)  # task_id, card_id
    task_finished = Signal(str, str, bool)  # task_id, card_id, ok
    task_skipped = Signal(str, str, str)  # task_id, card_id, reason

    def __init__(
        self,
        card_repo: CardRepository,
        task_repo: ScheduledTaskRepository,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cards = card_repo
        self._tasks = task_repo
        self._timer = QTimer(self)
        self._timer.setInterval(60_000)
        self._timer.timeout.connect(self._tick)
        self._agent_ctl = AgentThreadController(self)
        self._agent_ctl.opened.connect(self._on_agent_opened)
        self._agent_ctl.open_failed.connect(self._on_agent_open_failed)
        self._agent_ctl.finished.connect(self._on_agent_finished)
        self._running_task: ScheduledTask | None = None
        self._running_card: Card | None = None
        self._busy_cards: set[str] = set()
        self._pending_queue: list[ScheduledTask] = []

    def set_card_busy(self, card_id: str, busy: bool) -> None:
        if busy:
            self._busy_cards.add(card_id)
        else:
            self._busy_cards.discard(card_id)

    def start(self) -> None:
        self._timer.start()
        QTimer.singleShot(3000, self._tick)

    def stop(self) -> None:
        self._timer.stop()
        self._agent_ctl.cancel()
        self._agent_ctl.shutdown()

    def refresh(self) -> None:
        self._tick()

    def _tick(self) -> None:
        if self._running_task is not None:
            return
        now_iso = format_iso(datetime.now(timezone.utc))
        due = self._tasks.list_due(before_iso=now_iso)
        for task in due:
            if not is_task_due(task):
                continue
            if task.card_id in self._busy_cards:
                self._tasks.mark_skipped(
                    task,
                    reason="Пропущено: агент уже выполняет задачу",
                )
                self.task_skipped.emit(
                    task.id,
                    task.card_id,
                    "Агент уже занят — запуск отложен",
                )
                continue
            self._start_task(task)
            return
        if self._pending_queue and self._running_task is None:
            nxt = self._pending_queue.pop(0)
            if nxt.card_id not in self._busy_cards:
                self._start_task(nxt)

    def _start_task(self, task: ScheduledTask) -> None:
        card = self._cards.get(task.card_id)
        if card is None or card.phase != "published":
            self._tasks.mark_skipped(task, reason="Карточка недоступна")
            self.task_skipped.emit(task.id, task.card_id, "Агент не найден или не опубликован")
            return
        self._running_task = task
        self._running_card = card
        self._busy_cards.add(card.id)
        self.task_started.emit(task.id, card.id)
        set_confirm_callback(confirm_from_worker)
        self._agent_ctl.open_card(card)
        self._pending_prompt = self._scheduled_prompt(task)

    def _scheduled_prompt(self, task: ScheduledTask) -> str:
        title = (task.title or "Запланированная задача").strip()
        body = (task.prompt or "").strip()
        prefix = f"[Запланированная задача: {title}]"
        return f"{prefix}\n\n{body}" if body else prefix

    def _on_agent_opened(self, card_id: str, agent_id: str) -> None:
        task = self._running_task
        card = self._running_card
        if task is None or card is None or card.id != card_id:
            return
        if agent_id and card.cursor_agent_id != agent_id:
            self._cards.update_agent_id(card_id, agent_id)
        prompt = getattr(self, "_pending_prompt", "")
        self._agent_ctl.send(prompt, action=False)

    def _on_agent_finished(self, payload: object) -> None:
        task = self._running_task
        card = self._running_card
        if task is None or card is None:
            return
        ran_at = format_iso(datetime.now(timezone.utc))
        ok = isinstance(payload, dict) and payload.get("ok")
        if ok:
            text = str(payload.get("text") or "").strip()
            self._append_session_log(card, task, text, ok=True)
            self._tasks.mark_run(task, result=text or "Выполнено", ran_at_iso=ran_at)
            self.task_finished.emit(task.id, card.id, True)
        else:
            err = ""
            if isinstance(payload, dict):
                err = str(payload.get("error") or "Ошибка")
            self._append_session_log(card, task, err or "Ошибка", ok=False)
            self._tasks.mark_skipped(task, reason=err or "Ошибка выполнения")
            self.task_finished.emit(task.id, card.id, False)
        self._running_task = None
        self._running_card = None
        self._busy_cards.discard(card.id)
        reject_pending_confirm()
        QTimer.singleShot(500, self._tick)

    def _append_session_log(
        self,
        card: Card,
        task: ScheduledTask,
        result: str,
        *,
        ok: bool,
    ) -> None:
        entries = load_session_log(card.id, card.workspace_dir)
        title = task.title or "Запланированная задача"
        entries.append(("system", f"⏱ {title}"))
        entries.append(("user", task.prompt or title))
        kind = "agent" if ok else "error"
        entries.append((kind, result or ("Выполнено" if ok else "Ошибка")))
        save_session_log(card.id, entries, card.workspace_dir)

    def _on_agent_open_failed(self, error: str) -> None:
        task = self._running_task
        card = self._running_card
        if task is None or card is None:
            return
        self._tasks.mark_skipped(task, reason=error or "Не удалось открыть агента")
        self.task_skipped.emit(task.id, card.id, error or "Ошибка подключения")
        self._running_task = None
        self._running_card = None
        self._busy_cards.discard(card.id)
        QTimer.singleShot(500, self._tick)
