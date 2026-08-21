from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.config import CARDS_DB, ensure_data_dirs
from app.models import Card

_JSON_COLUMNS = (
    "functions_json",
    "passport_json",
    "playbook_draft_json",
    "playbook_json",
    "demo_json",
    "triggers_json",
    "kpi_json",
)


class CardRepository:
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
                CREATE TABLE IF NOT EXISTS cards (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    regulation_path TEXT NOT NULL DEFAULT '',
                    regulation_text TEXT NOT NULL DEFAULT '',
                    ui_spec_json TEXT NOT NULL DEFAULT '{}',
                    rules_prompt TEXT NOT NULL DEFAULT '',
                    cursor_agent_id TEXT NOT NULL DEFAULT '',
                    workspace_dir TEXT NOT NULL DEFAULT '',
                    phase TEXT NOT NULL DEFAULT 'intake',
                    functions_json TEXT NOT NULL DEFAULT '{}',
                    passport_json TEXT NOT NULL DEFAULT '{}',
                    playbook_draft_json TEXT NOT NULL DEFAULT '{}',
                    playbook_json TEXT NOT NULL DEFAULT '{}',
                    demo_json TEXT NOT NULL DEFAULT '{}',
                    triggers_json TEXT NOT NULL DEFAULT '{}',
                    kpi_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._migrate_columns(conn)

    def _migrate_columns(self, conn: sqlite3.Connection) -> None:
        """Добавить новые колонки в существующую БД без потери данных."""
        existing = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(cards)").fetchall()
        }
        additions: dict[str, str] = {
            "phase": "TEXT NOT NULL DEFAULT 'intake'",
            "functions_json": "TEXT NOT NULL DEFAULT '{}'",
            "passport_json": "TEXT NOT NULL DEFAULT '{}'",
            "playbook_draft_json": "TEXT NOT NULL DEFAULT '{}'",
            "playbook_json": "TEXT NOT NULL DEFAULT '{}'",
            "demo_json": "TEXT NOT NULL DEFAULT '{}'",
            "triggers_json": "TEXT NOT NULL DEFAULT '{}'",
            "kpi_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, ddl in additions.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE cards ADD COLUMN {column} {ddl}")
        if "phase" in existing or "phase" in additions:
            conn.execute(
                """
                UPDATE cards
                SET phase = CASE
                    WHEN phase IS NULL OR phase = '' THEN
                        CASE WHEN cursor_agent_id != '' THEN 'published' ELSE 'intake' END
                    ELSE phase
                END
                """
            )

    def list_cards(self) -> list[Card]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cards ORDER BY updated_at DESC"
            ).fetchall()
        return [Card.from_row(dict(row)) for row in rows]

    def get(self, card_id: str) -> Card | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        return Card.from_row(dict(row)) if row else None

    def save(self, card: Card) -> Card:
        card.touch()
        payload = (
            card.id,
            card.title,
            card.summary,
            card.regulation_path,
            card.regulation_text,
            json.dumps(card.ui_spec.model_dump(mode="json"), ensure_ascii=False),
            card.rules_prompt or card.ui_spec.rules_prompt,
            card.cursor_agent_id,
            card.workspace_dir,
            card.phase,
            json.dumps(card.functions.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(card.passport.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(card.playbook_draft.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(card.playbook.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(card.demo.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(card.triggers.model_dump(mode="json"), ensure_ascii=False),
            json.dumps(card.kpi.model_dump(mode="json"), ensure_ascii=False),
            card.created_at,
            card.updated_at,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cards (
                    id, title, summary, regulation_path, regulation_text,
                    ui_spec_json, rules_prompt, cursor_agent_id, workspace_dir,
                    phase, functions_json, passport_json, playbook_draft_json,
                    playbook_json, demo_json, triggers_json, kpi_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    summary=excluded.summary,
                    regulation_path=excluded.regulation_path,
                    regulation_text=excluded.regulation_text,
                    ui_spec_json=excluded.ui_spec_json,
                    rules_prompt=excluded.rules_prompt,
                    cursor_agent_id=excluded.cursor_agent_id,
                    workspace_dir=excluded.workspace_dir,
                    phase=excluded.phase,
                    functions_json=excluded.functions_json,
                    passport_json=excluded.passport_json,
                    playbook_draft_json=excluded.playbook_draft_json,
                    playbook_json=excluded.playbook_json,
                    demo_json=excluded.demo_json,
                    triggers_json=excluded.triggers_json,
                    kpi_json=excluded.kpi_json,
                    updated_at=excluded.updated_at
                """,
                payload,
            )
        return card

    def delete(self, card_id: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cards WHERE id = ?", (card_id,))

    def update_agent_id(self, card_id: str, agent_id: str) -> None:
        card = self.get(card_id)
        if card is None:
            return
        card.cursor_agent_id = agent_id
        self.save(card)

    def update_phase(self, card_id: str, phase: str) -> None:
        card = self.get(card_id)
        if card is None:
            return
        card.phase = phase  # type: ignore[assignment]
        self.save(card)
