"""Чтение базы Constructor. Только SELECT, транзакции read-only."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url

from app.config import settings

# JSON-поля разбираются в SQL: local_run/plan_json у агентов бывают большими.
_PUBLISHED_CANDIDATES = text(
    """
    SELECT
        w.id,
        w.user_id,
        w.title,
        w.phase,
        w.document_name,
        left(w.notes, 400) AS notes,
        w.updated_at,
        w.plan_json ->> 'title' AS plan_title,
        w.plan_json ->> 'goal' AS plan_goal,
        w.plan_json -> 'runtime' -> 'tools' AS runtime_tools,
        w.local_run ->> 'published' AS published,
        w.local_run ->> 'status' AS status,
        w.local_run ->> 'deleted' AS deleted,
        w.local_run ->> 'paused' AS paused,
        w.local_run ->> 'kind' AS kind,
        w.local_run ->> 'unformed' AS unformed,
        w.local_run ->> 'trigger_summary' AS trigger_summary,
        w.local_run -> 'tools' AS tools,
        w.local_run -> 'schedule_draft' ->> 'goal' AS draft_goal,
        u.fio,
        u.position,
        u.department,
        u.avatar_path,
        u.updated_at AS user_updated_at
    FROM workflows w
    JOIN users u ON u.id = w.user_id
    WHERE w.phase <> 'deleted'
    ORDER BY w.updated_at DESC
    """
)


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return create_engine(
        settings.constructor_database_url,
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
        pool_recycle=1800,
        future=True,
        connect_args={
            "connect_timeout": settings.constructor_connect_timeout,
            "options": "-c statement_timeout=20000",
        },
    )


def database_label() -> str:
    url = make_url(settings.constructor_database_url)
    return f"{url.host}:{url.port or 5432}/{url.database}"


_AGENT_DETAIL = text(
    """
    SELECT
        w.id,
        w.user_id,
        w.title,
        w.phase,
        w.document_name,
        left(w.notes, 8000) AS notes,
        w.updated_at,
        w.plan_json ->> 'title' AS plan_title,
        left(w.plan_json ->> 'goal', 8000) AS plan_goal,
        left(w.plan_json -> 'playbook' ->> 'instructions', 20000) AS plan_instructions,
        left(w.plan_json -> 'playbook' ->> 'expected_result', 8000) AS plan_expected,
        left(w.local_run -> 'playbook' ->> 'instructions', 20000) AS run_instructions,
        left(w.local_run -> 'playbook' ->> 'example_run', 20000) AS run_example,
        left(w.plan_json -> 'playbook' ->> 'example_run', 20000) AS plan_example,
        left(w.local_run -> 'playbook' ->> 'chain', 20000) AS run_chain,
        left(w.plan_json -> 'playbook' ->> 'chain', 20000) AS plan_chain,
        w.local_run -> 'playbook' -> 'steps' AS run_steps,
        w.plan_json -> 'playbook' -> 'steps' AS plan_steps,
        w.local_run -> 'playbook' -> 'tools' AS playbook_tools,
        w.plan_json -> 'playbook' -> 'tools' AS plan_playbook_tools,
        left(w.local_run -> 'playbook' ->> 'expected_result', 8000) AS run_expected,
        w.plan_json -> 'runtime' -> 'tools' AS runtime_tools,
        w.local_run ->> 'published' AS published,
        w.local_run ->> 'status' AS status,
        w.local_run ->> 'deleted' AS deleted,
        w.local_run ->> 'paused' AS paused,
        w.local_run ->> 'kind' AS kind,
        w.local_run ->> 'unformed' AS unformed,
        w.local_run ->> 'trigger_summary' AS trigger_summary,
        w.local_run -> 'tools' AS tools,
        w.local_run -> 'schedule_draft' ->> 'goal' AS draft_goal,
        u.fio,
        u.position,
        u.department
    FROM workflows w
    JOIN users u ON u.id = w.user_id
    WHERE w.id = :agent_id
    """
)


def _read(statement: Any, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with _engine().connect().execution_options(postgresql_readonly=True) as conn:
        return [dict(row) for row in conn.execute(statement, parameters or {}).mappings()]


def fetch_published_candidates() -> list[dict[str, Any]]:
    return _read(_PUBLISHED_CANDIDATES)


def fetch_agent_detail(agent_id: str) -> dict[str, Any] | None:
    rows = _read(_AGENT_DETAIL, {"agent_id": agent_id})
    return rows[0] if rows else None
