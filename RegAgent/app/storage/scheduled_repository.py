from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from app.config import CARDS_DB, ensure_data_dirs
from app.models import ScheduledTask
from app.scheduler.logic import compute_next_run, format_iso, parse_iso


class ScheduledTaskRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or CARDS_DB
        ensure_data_dirs()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_tasks (
                    id TEXT PRIMARY KEY,
                    card_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    prompt TEXT NOT NULL DEFAULT '',
                    trigger_type TEXT NOT NULL DEFAULT 'once',
                    trigger_config_json TEXT NOT NULL DEFAULT '{}',
                    next_run_at TEXT NOT NULL DEFAULT '',
                    last_run_at TEXT,
                    last_result TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (card_id) REFERENCES cards(id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_card
                ON scheduled_tasks(card_id)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_next_run
                ON scheduled_tasks(next_run_at)
                """
            )

    def list_all(self, *, enabled_only: bool = False) -> list[ScheduledTask]:
        query = "SELECT * FROM scheduled_tasks"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY next_run_at ASC, created_at ASC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [ScheduledTask.from_row(dict(row)) for row in rows]

    def list_for_card(self, card_id: str) -> list[ScheduledTask]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE card_id = ? ORDER BY next_run_at ASC",
                (card_id,),
            ).fetchall()
        return [ScheduledTask.from_row(dict(row)) for row in rows]

    def list_due(self, *, before_iso: str) -> list[ScheduledTask]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE enabled = 1 AND next_run_at != '' AND next_run_at <= ?
                ORDER BY next_run_at ASC
                """,
                (before_iso,),
            ).fetchall()
        return [ScheduledTask.from_row(dict(row)) for row in rows]

    def list_upcoming(self, limit: int = 20) -> list[ScheduledTask]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE enabled = 1 AND next_run_at != ''
                ORDER BY next_run_at ASC
                LIMIT ?
                """,
                (max(1, limit),),
            ).fetchall()
        return [ScheduledTask.from_row(dict(row)) for row in rows]

    def list_in_range(self, start_iso: str, end_iso: str) -> list[ScheduledTask]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM scheduled_tasks
                WHERE next_run_at >= ? AND next_run_at < ?
                ORDER BY next_run_at ASC
                """,
                (start_iso, end_iso),
            ).fetchall()
        return [ScheduledTask.from_row(dict(row)) for row in rows]

    def count_by_card(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT card_id, COUNT(*) AS cnt
                FROM scheduled_tasks
                WHERE enabled = 1
                GROUP BY card_id
                """
            ).fetchall()
        return {str(row["card_id"]): int(row["cnt"]) for row in rows}

    def get(self, task_id: str) -> ScheduledTask | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
            ).fetchone()
        return ScheduledTask.from_row(dict(row)) if row else None

    def save(self, task: ScheduledTask) -> ScheduledTask:
        if not parse_iso(task.next_run_at):
            nxt = compute_next_run(task)
            task.next_run_at = format_iso(nxt) if nxt else task.next_run_at
        payload = (
            task.id,
            task.card_id,
            task.title,
            task.prompt,
            task.trigger_type,
            json.dumps(task.trigger_config, ensure_ascii=False),
            task.next_run_at,
            task.last_run_at,
            task.last_result,
            1 if task.enabled else 0,
            task.created_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_tasks (
                    id, card_id, title, prompt, trigger_type, trigger_config_json,
                    next_run_at, last_run_at, last_result, enabled, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    card_id=excluded.card_id,
                    title=excluded.title,
                    prompt=excluded.prompt,
                    trigger_type=excluded.trigger_type,
                    trigger_config_json=excluded.trigger_config_json,
                    next_run_at=excluded.next_run_at,
                    last_run_at=excluded.last_run_at,
                    last_result=excluded.last_result,
                    enabled=excluded.enabled
                """,
                payload,
            )
        return task

    def delete(self, task_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))

    def delete_for_card(self, card_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM scheduled_tasks WHERE card_id = ?", (card_id,))

    def mark_run(
        self,
        task: ScheduledTask,
        *,
        result: str,
        ran_at_iso: str,
    ) -> ScheduledTask:
        task.last_run_at = ran_at_iso
        task.last_result = (result or "")[:4000] or None
        if task.trigger_type == "once":
            task.enabled = False
            task.next_run_at = ""
        else:
            nxt = compute_next_run(task, after_run=True)
            task.next_run_at = format_iso(nxt) if nxt else ""
            if not task.next_run_at:
                task.enabled = False
        return self.save(task)

    def mark_skipped(self, task: ScheduledTask, *, reason: str) -> ScheduledTask:
        task.last_result = (reason or "")[:4000]
        if task.trigger_type == "once":
            return self.save(task)
        nxt = compute_next_run(task, after_run=False)
        if nxt:
            task.next_run_at = format_iso(nxt)
        return self.save(task)
