"""Общие агенты платформы в базе Constructor (схема turbotest): их видят и запускают все пользователи TurboTester."""

from __future__ import annotations

import getpass
import json
import logging
import socket
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings
from app.constructor.db import database_label
from app.platform.passport import AgentPassport, clean_icon
from app.platform.sessions import LastRun, PlatformAgent, parse_stamp, store

logger = logging.getLogger(__name__)

TABLE = "turbotest.agents"
LIST_LIMIT = 200
CACHE_SECONDS = 5.0
# После ошибки базы не дёргаем её на каждый опрос списка.
RETRY_AFTER_SECONDS = 30.0

_DDL = (
    "CREATE SCHEMA IF NOT EXISTS turbotest",
    """
    CREATE TABLE IF NOT EXISTS turbotest.agents (
        id uuid PRIMARY KEY,
        config_id text NOT NULL,
        config_title text NOT NULL DEFAULT '',
        title text NOT NULL,
        request text NOT NULL DEFAULT '',
        instruction text NOT NULL,
        tools jsonb NOT NULL DEFAULT '[]'::jsonb,
        last_run jsonb,
        runs integer NOT NULL DEFAULT 0,
        author text NOT NULL DEFAULT '',
        author_host text NOT NULL DEFAULT '',
        created_at timestamptz NOT NULL,
        updated_at timestamptz NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS agents_config_updated ON turbotest.agents (config_id, updated_at DESC)",
    # Паспорт агента (формат Constructor) и SVG-иконка — их заполняет облачный агент Cursor.
    "ALTER TABLE turbotest.agents ADD COLUMN IF NOT EXISTS passport jsonb",
    "ALTER TABLE turbotest.agents ADD COLUMN IF NOT EXISTS icon_svg text NOT NULL DEFAULT ''",
    # Удаление — пометка, а не DELETE: иначе локальная копия на другом компьютере записала бы агента заново.
    "ALTER TABLE turbotest.agents ADD COLUMN IF NOT EXISTS deleted_at timestamptz",
)

# Копия агента без паспорта (старая или с другого компьютера) не стирает уже записанный паспорт.
_UPSERT = text(
    """
    INSERT INTO turbotest.agents (
        id, config_id, config_title, title, request, instruction, tools, last_run,
        runs, author, author_host, passport, icon_svg, created_at, updated_at
    ) VALUES (
        :id, :config_id, :config_title, :title, :request, :instruction, CAST(:tools AS jsonb),
        CAST(:last_run AS jsonb), :runs, :author, :author_host, CAST(:passport AS jsonb), :icon_svg,
        :created_at, now()
    )
    ON CONFLICT (id) DO UPDATE SET
        config_title = EXCLUDED.config_title,
        title = EXCLUDED.title,
        instruction = EXCLUDED.instruction,
        tools = EXCLUDED.tools,
        last_run = EXCLUDED.last_run,
        runs = turbotest.agents.runs + :added_runs,
        passport = COALESCE(EXCLUDED.passport, turbotest.agents.passport),
        icon_svg = CASE WHEN EXCLUDED.passport IS NULL THEN turbotest.agents.icon_svg ELSE EXCLUDED.icon_svg END,
        updated_at = now()
    """
)

_COLUMNS = (
    "id::text AS id, config_id, config_title, title, request, instruction, tools, last_run, "
    "runs, author, author_host, passport, icon_svg, created_at, updated_at, deleted_at"
)
_LIST = text(
    f"SELECT {_COLUMNS} FROM turbotest.agents WHERE config_id = :config_id "
    "ORDER BY updated_at DESC LIMIT :limit"
)
_LIST_STORED = text(
    "SELECT id::text AS id, config_id, config_title, title "
    "FROM turbotest.agents WHERE deleted_at IS NULL ORDER BY updated_at DESC"
)
_ONE = text(f"SELECT {_COLUMNS} FROM turbotest.agents WHERE id = CAST(:agent_id AS uuid)")
_DELETE = text(
    "UPDATE turbotest.agents SET deleted_at = now(), updated_at = now() "
    "WHERE id = CAST(:agent_id AS uuid) AND deleted_at IS NULL"
)


class SharedUnavailable(RuntimeError):
    pass


_lock = threading.Lock()
_ready = False
_failed_at = 0.0
_error = ""
_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
# Агенты, чью новую версию не удалось записать: локальная копия свежее базы, её и досылаем.
_pending: set[str] = set()
_writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="turbotest-shared")


def enabled() -> bool:
    return settings.platform_shared_enabled


def source() -> str:
    return f"{database_label()} · {TABLE}"


def author_name() -> str:
    return settings.constructor_user_fio.strip() or getpass.getuser()


def host_name() -> str:
    return socket.gethostname()


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return create_engine(
        settings.constructor_database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=1,
        pool_recycle=1800,
        future=True,
        connect_args={
            "connect_timeout": settings.constructor_connect_timeout,
            "options": "-c statement_timeout=15000",
        },
    )


def _message(exc: Exception) -> str:
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def _guard() -> None:
    if not enabled():
        raise SharedUnavailable("Общая база агентов выключена")
    with _lock:
        if _error and time.monotonic() - _failed_at < RETRY_AFTER_SECONDS:
            raise SharedUnavailable(_error)


def _failed(exc: Exception) -> SharedUnavailable:
    global _failed_at, _error
    with _lock:
        _failed_at = time.monotonic()
        _error = f"Общая база агентов недоступна: {_message(exc)}"
        return SharedUnavailable(_error)


def _recovered() -> None:
    global _error
    with _lock:
        _error = ""


def _ensure_table() -> None:
    global _ready
    if _ready:
        return
    with _engine().begin() as conn:
        for statement in _DDL:
            conn.execute(text(statement))
    _ready = True


def _upsert(payload: dict[str, Any]) -> None:
    _ensure_table()
    with _engine().begin() as conn:
        conn.execute(_UPSERT, payload)


def _fetch_rows(config_id: str) -> list[dict[str, Any]]:
    _ensure_table()
    with _engine().connect() as conn:
        rows = conn.execute(_LIST, {"config_id": config_id, "limit": LIST_LIMIT}).mappings()
        return [dict(row) for row in rows]


def stored_agents() -> tuple[list[dict[str, str]], str]:
    """Агенты платформы, уже записанные в turbotest.agents. Только чтение."""
    if not enabled():
        return [], ""
    try:
        _guard()
        _ensure_table()
        with _engine().connect() as conn:
            rows = conn.execute(_LIST_STORED).mappings()
            items = [
                {
                    "id": str(row["id"]),
                    "title": str(row["title"] or "").strip() or "Без названия",
                    "config_id": str(row["config_id"] or ""),
                    "config_title": str(row["config_title"] or ""),
                }
                for row in rows
            ]
        _recovered()
        return items, ""
    except SharedUnavailable as exc:
        return [], str(exc)
    except Exception as exc:  # noqa: BLE001
        return [], str(_failed(exc))


def _fetch_one(agent_id: str) -> dict[str, Any] | None:
    _ensure_table()
    with _engine().connect() as conn:
        row = conn.execute(_ONE, {"agent_id": agent_id}).mappings().first()
        return dict(row) if row else None


# -- модель ---------------------------------------------------------------
def tools_summary(run: LastRun | None) -> list[dict[str, Any]]:
    """Какие инструменты агент вызывал в последнем прогоне: сколько раз и сколько из них с ошибкой."""
    if run is None:
        return []
    calls = Counter(step.name for step in run.steps)
    errors = Counter(step.name for step in run.steps if step.status == "error")
    return [{"name": name, "calls": count, "errors": errors[name]} for name, count in calls.items()]


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _from_row(row: dict[str, Any]) -> tuple[PlatformAgent, dict[str, Any]]:
    last_run = _json(row.get("last_run"))
    passport = _json(row.get("passport"))
    agent = PlatformAgent(
        id=str(row["id"]),
        title=row["title"],
        instruction=row["instruction"],
        config_id=row["config_id"],
        created_at=_iso(row["created_at"]),
        request=row.get("request") or "",
        last_run=LastRun.model_validate(last_run) if last_run else None,
        author=row.get("author") or "",
        updated_at=_iso(row["updated_at"]),
        runs=int(row.get("runs") or 0),
        passport=AgentPassport.from_payload(passport) if isinstance(passport, dict) else None,
        icon_svg=clean_icon(row.get("icon_svg")),
        profile_status="ready" if isinstance(passport, dict) else "",
    )
    extra = {"author_host": row.get("author_host") or "", "tools": _json(row.get("tools")) or []}
    return agent, extra


def _payload(agent: PlatformAgent, config_title: str, added_runs: int) -> dict[str, Any]:
    run = agent.last_run.model_dump() if agent.last_run else None
    return {
        "id": agent.id,
        "config_id": agent.config_id,
        "config_title": config_title,
        "title": agent.title,
        "request": agent.request,
        "instruction": agent.instruction,
        "tools": json.dumps(tools_summary(agent.last_run), ensure_ascii=False),
        "last_run": json.dumps(run, ensure_ascii=False) if run else None,
        "runs": agent.runs,
        "added_runs": added_runs,
        "author": agent.author or author_name(),
        "author_host": host_name(),
        "passport": agent.passport.model_dump_json() if agent.passport else None,
        "icon_svg": agent.icon_svg,
        "created_at": parse_stamp(agent.created_at),
    }


# -- операции -------------------------------------------------------------
def _publish_now(payload: dict[str, Any]) -> None:
    try:
        _upsert(payload)
    except Exception as exc:  # noqa: BLE001 — база общая и бывает недоступна, прогон от этого не падает
        _pending.add(payload["id"])
        logger.warning("shared agent %s not published: %s", payload["id"], _failed(exc))
        return
    _pending.discard(payload["id"])
    _recovered()
    _cache.pop(payload["config_id"], None)


def publish(agent: PlatformAgent, config_title: str, *, added_runs: int = 0) -> None:
    """Отправить агента с инструкцией в общую базу. В фоне: запросы API не ждут сеть."""
    if not enabled() or not agent.instruction.strip():
        return
    _writer.submit(_publish_now, _payload(agent, config_title, added_runs))


def fetch_agent(agent_id: str) -> PlatformAgent | None:
    """Свежая версия агента из общей базы; None — если его там нет или база недоступна."""
    if not enabled() or agent_id in _pending:
        return None
    try:
        UUID(agent_id)
    except ValueError:
        return None
    try:
        _guard()
        row = _fetch_one(agent_id)
    except SharedUnavailable:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("shared agent %s not fetched: %s", agent_id, _failed(exc))
        return None
    _recovered()
    if row and row.get("deleted_at"):
        store.delete_agent(agent_id)
        return None
    return _from_row(row)[0] if row else None


def _delete_now(agent_id: str) -> None:
    _ensure_table()
    with _engine().begin() as conn:
        conn.execute(_DELETE, {"agent_id": agent_id})


def delete(agent_id: str) -> None:
    """Пометить агента удалённым для всех. SharedUnavailable — база недоступна, удалять нельзя.

    Через тот же поток, что и publish: запись, стоящая в очереди, не воскресит агента после пометки.
    """
    if not enabled():
        return
    try:
        UUID(agent_id)
    except ValueError:
        return
    _guard()
    try:
        _writer.submit(_delete_now, agent_id).result(timeout=30)
    except Exception as exc:  # noqa: BLE001
        raise _failed(exc) from exc
    _recovered()
    _pending.discard(agent_id)
    _cache.clear()


def list_agents(
    config_id: str, local: list[PlatformAgent], config_title: str
) -> tuple[list[dict[str, Any]], str]:
    """Агенты конфигурации: общие из базы плюс локальные, которых там ещё нет. Возвращает (items, ошибку)."""
    error = ""
    rows: list[dict[str, Any]] = []
    if enabled():
        try:
            _guard()
            cached = _cache.get(config_id)
            if cached and time.monotonic() - cached[0] < CACHE_SECONDS:
                rows = cached[1]
            else:
                rows = _fetch_rows(config_id)
                _cache[config_id] = (time.monotonic(), rows)
                _recovered()
        except SharedUnavailable as exc:
            error = str(exc)
        except Exception as exc:  # noqa: BLE001
            error = str(_failed(exc))

    mine = author_name()
    local_by_id = {agent.id: agent for agent in local}
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        if row.get("deleted_at"):
            # Автор удалил агента на другом компьютере — локальная копия здесь тоже больше не нужна.
            if row["id"] in local_by_id:
                store.delete_agent(row["id"])
                local_by_id.pop(row["id"])
            seen.add(str(row["id"]))
            continue
        remote, extra = _from_row(row)
        own = local_by_id.get(remote.id)
        if own is not None and own.id in _pending and not error:
            publish(own, config_title)
        # Паспорт составляется или не удался на этом компьютере — база об этом ещё не знает.
        if own is not None and own.profile_status in ("pending", "error"):
            remote.profile_status, remote.profile_error = own.profile_status, own.profile_error
        items.append(_item(remote, extra, shared=True, mine=remote.author == mine))
        seen.add(remote.id)
    for agent in local:
        if agent.id in seen:
            continue
        if not error:
            publish(agent, config_title)
        extra = {"author_host": host_name(), "tools": tools_summary(agent.last_run)}
        items.append(_item(agent, extra, shared=False, mine=not agent.author or agent.author == mine))
    items.sort(key=lambda item: parse_stamp(item["updated_at"] or item["created_at"]), reverse=True)
    return items, error


def _item(agent: PlatformAgent, extra: dict[str, Any], *, shared: bool, mine: bool) -> dict[str, Any]:
    run = agent.last_run
    return {
        "id": agent.id,
        "title": agent.title,
        "config_id": agent.config_id,
        "request": agent.request,
        "instruction": agent.instruction,
        "author": agent.author,
        "author_host": extra["author_host"],
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
        "runs": agent.runs,
        "tools": extra["tools"],
        "last_run": (
            {
                "status": run.status,
                "finished_at": run.finished_at,
                "steps": len(run.steps),
                "error": run.error,
            }
            if run
            else None
        ),
        "passport": agent.passport.model_dump() if agent.passport else None,
        "icon_svg": agent.icon_svg,
        "profile_status": agent.profile_status,
        "profile_error": agent.profile_error,
        "shared": shared,
        "mine": mine,
    }
