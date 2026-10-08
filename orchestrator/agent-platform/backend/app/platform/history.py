"""История прогонов в общей базе (turbotest.runs): диалог, файлы каталога, конфигурация на момент
запуска и статистика — графики ресурсов, журнал взаимодействия, контекст. Пишут все компьютеры,
читают тоже все: в «Истории» видны запуски и с этого устройства, и с других.

Пока база недоступна, прогон по-прежнему остаётся в JSON на диске и дозаливается при старте сервера.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from uuid import UUID

import psutil
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import TEXT as PG_TEXT
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.platform.attachments import Attachment
from app.platform.sessions import PlatformSession, SessionEvent, SessionInsights, store

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 2_000_000
LIST_LIMIT = 500
# После ошибки базы не дёргаем её на каждый опрос «Истории».
RETRY_AFTER_SECONDS = 30.0
LIST_CACHE_SECONDS = 4.0
RUN_CACHE_SECONDS = 60.0
RUN_CACHE_SIZE = 16
_SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".cursor"}
_TERMINAL = {"finished", "error", "cancelled"}

_DDL = (
    "CREATE SCHEMA IF NOT EXISTS turbotest",
    """
    CREATE TABLE IF NOT EXISTS turbotest.runs (
        id               uuid PRIMARY KEY,
        config_id        text NOT NULL,
        config_title     text NOT NULL,
        source           text NOT NULL CHECK (source IN ('custom', 'constructor')),
        agent_id         text NOT NULL,
        agent_title      text NOT NULL,
        prompt           text NOT NULL,
        status           text NOT NULL CHECK (status IN ('running', 'finished', 'error', 'cancelled')),
        error            text NOT NULL DEFAULT '',
        sdk_agent_id     text NOT NULL DEFAULT '',
        turns            integer NOT NULL DEFAULT 0,
        model            text NOT NULL DEFAULT '',
        entry            jsonb NOT NULL DEFAULT '[]',
        config_manifest  jsonb NOT NULL DEFAULT '{}',
        created_at       timestamptz NOT NULL,
        updated_at       timestamptz NOT NULL,
        finished_at      timestamptz
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS turbotest.run_events (
        run_id        uuid NOT NULL REFERENCES turbotest.runs (id) ON DELETE CASCADE,
        seq           integer NOT NULL,
        rev           integer NOT NULL,
        turn          integer NOT NULL,
        type          text NOT NULL,
        body          text NOT NULL DEFAULT '',
        name          text NOT NULL DEFAULT '',
        status        text NOT NULL DEFAULT '',
        call_id       text NOT NULL DEFAULT '',
        args          text NOT NULL DEFAULT '',
        result        text NOT NULL DEFAULT '',
        args_chars    integer NOT NULL DEFAULT 0,
        result_chars  integer NOT NULL DEFAULT 0,
        PRIMARY KEY (run_id, seq)
    )
    """,
    "CREATE INDEX IF NOT EXISTS run_events_rev_idx ON turbotest.run_events (run_id, rev)",
    """
    CREATE TABLE IF NOT EXISTS turbotest.run_files (
        run_id           uuid NOT NULL REFERENCES turbotest.runs (id) ON DELETE CASCADE,
        path             text NOT NULL,
        size_bytes       bigint NOT NULL,
        sha256           text NOT NULL,
        body             bytea,
        skipped_reason   text NOT NULL DEFAULT '',
        PRIMARY KEY (run_id, path)
    )
    """,
    "COMMENT ON TABLE turbotest.runs IS 'Прогон: инструкция и конфигурация, с которой он стартовал'",
    "COMMENT ON TABLE turbotest.run_events IS 'Диалог прогона, включая уточнения после инструкции'",
    "COMMENT ON TABLE turbotest.run_files IS 'Файлы рабочего каталога на конец прогона'",
    "CREATE INDEX IF NOT EXISTS runs_updated_idx ON turbotest.runs (updated_at DESC)",
    # Кто и где запускал, план прогона и железо компьютера — для просмотра с другого устройства.
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS author text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS author_host text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS plan_turn integer NOT NULL DEFAULT 0",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS plan text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.runs ADD COLUMN IF NOT EXISTS machine jsonb NOT NULL DEFAULT '{}'",
    "ALTER TABLE turbotest.run_events ADD COLUMN IF NOT EXISTS label text NOT NULL DEFAULT ''",
    "ALTER TABLE turbotest.run_events ADD COLUMN IF NOT EXISTS attachments jsonb NOT NULL DEFAULT '[]'",
    "ALTER TABLE turbotest.run_events ADD COLUMN IF NOT EXISTS parent text NOT NULL DEFAULT ''",
    """
    CREATE TABLE IF NOT EXISTS turbotest.run_insights (
        run_id      uuid PRIMARY KEY REFERENCES turbotest.runs (id) ON DELETE CASCADE,
        body        bytea NOT NULL,
        size_bytes  bigint NOT NULL,
        updated_at  timestamptz NOT NULL
    )
    """,
    "COMMENT ON TABLE turbotest.run_insights IS "
    "'Статистика прогона (gzip JSON): ресурсы, скачки, журнал взаимодействия, контекст'",
)

_UPSERT_RUN = text(
    """
    INSERT INTO turbotest.runs (
        id, config_id, config_title, source, agent_id, agent_title, prompt,
        status, error, sdk_agent_id, turns, model, entry, config_manifest,
        author, author_host, plan_turn, plan, machine,
        created_at, updated_at, finished_at
    ) VALUES (
        CAST(:id AS uuid), :config_id, :config_title, :source, :agent_id, :agent_title, :prompt,
        :status, :error, :sdk_agent_id, :turns, :model, :entry, :config_manifest,
        :author, :author_host, :plan_turn, :plan, :machine,
        :created_at, :updated_at, :finished_at
    )
    ON CONFLICT (id) DO UPDATE SET
        config_title = EXCLUDED.config_title,
        agent_title = EXCLUDED.agent_title,
        prompt = EXCLUDED.prompt,
        status = EXCLUDED.status,
        error = EXCLUDED.error,
        sdk_agent_id = EXCLUDED.sdk_agent_id,
        turns = EXCLUDED.turns,
        model = EXCLUDED.model,
        entry = EXCLUDED.entry,
        config_manifest = EXCLUDED.config_manifest,
        author = EXCLUDED.author,
        author_host = EXCLUDED.author_host,
        plan_turn = EXCLUDED.plan_turn,
        plan = EXCLUDED.plan,
        machine = EXCLUDED.machine,
        updated_at = EXCLUDED.updated_at,
        finished_at = EXCLUDED.finished_at
    """
).bindparams(
    bindparam("entry", type_=JSONB()),
    bindparam("config_manifest", type_=JSONB()),
    bindparam("machine", type_=JSONB()),
)

_UPSERT_EVENT = text(
    """
    INSERT INTO turbotest.run_events (
        run_id, seq, rev, turn, type, body, name, status, call_id, args, result, args_chars, result_chars,
        label, attachments, parent
    ) VALUES (
        CAST(:run_id AS uuid), :seq, :rev, :turn, :type, :body, :name, :status, :call_id,
        :args, :result, :args_chars, :result_chars, :label, :attachments, :parent
    )
    ON CONFLICT (run_id, seq) DO UPDATE SET
        rev = EXCLUDED.rev,
        turn = EXCLUDED.turn,
        type = EXCLUDED.type,
        body = EXCLUDED.body,
        name = EXCLUDED.name,
        status = EXCLUDED.status,
        call_id = EXCLUDED.call_id,
        args = EXCLUDED.args,
        result = EXCLUDED.result,
        args_chars = EXCLUDED.args_chars,
        result_chars = EXCLUDED.result_chars,
        label = EXCLUDED.label,
        attachments = EXCLUDED.attachments,
        parent = EXCLUDED.parent
    """
).bindparams(bindparam("attachments", type_=JSONB()))

_UPSERT_INSIGHTS = text(
    """
    INSERT INTO turbotest.run_insights (run_id, body, size_bytes, updated_at)
    VALUES (CAST(:run_id AS uuid), :body, :size_bytes, now())
    ON CONFLICT (run_id) DO UPDATE SET
        body = EXCLUDED.body,
        size_bytes = EXCLUDED.size_bytes,
        updated_at = now()
    """
)

_RUN_COLUMNS = (
    "id::text AS id, config_id, config_title, source, agent_id, agent_title, prompt, status, error, "
    "sdk_agent_id, turns, plan_turn, model, author, author_host, created_at, updated_at"
)
_LIST_RUNS = text(f"SELECT {_RUN_COLUMNS} FROM turbotest.runs ORDER BY updated_at DESC LIMIT :limit")
_ONE_RUN = text(
    f"SELECT {_RUN_COLUMNS}, plan, entry, machine FROM turbotest.runs WHERE id = CAST(:id AS uuid)"
)
_RUN_EVENTS = text(
    """
    SELECT seq, rev, turn, type, body, name, status, call_id, args, result, args_chars, result_chars,
           label, attachments, parent
    FROM turbotest.run_events WHERE run_id = CAST(:id AS uuid) ORDER BY seq
    """
)
_RUN_INSIGHTS = text("SELECT body FROM turbotest.run_insights WHERE run_id = CAST(:id AS uuid)")
_RUN_FILE = text(
    "SELECT body FROM turbotest.run_files WHERE run_id = CAST(:id AS uuid) AND path = :path AND body IS NOT NULL"
)
_SYNC_STATE = text(
    """
    SELECT r.id::text AS id, r.updated_at, r.author_host, (i.run_id IS NOT NULL) AS has_insights
    FROM turbotest.runs r LEFT JOIN turbotest.run_insights i ON i.run_id = r.id
    WHERE r.id = ANY(CAST(:ids AS uuid[]))
    """
).bindparams(bindparam("ids", type_=ARRAY(PG_TEXT())))

_DELETE_FILES = text("DELETE FROM turbotest.run_files WHERE run_id = CAST(:run_id AS uuid)")

_DELETE_OTHER_FILES = text(
    """
    DELETE FROM turbotest.run_files
    WHERE run_id = CAST(:run_id AS uuid)
      AND NOT (path = ANY(:paths))
    """
).bindparams(bindparam("paths", type_=ARRAY(PG_TEXT())))

_UPSERT_FILE = text(
    """
    INSERT INTO turbotest.run_files (run_id, path, size_bytes, sha256, body, skipped_reason)
    VALUES (CAST(:run_id AS uuid), :path, :size_bytes, :sha256, :body, :skipped_reason)
    ON CONFLICT (run_id, path) DO UPDATE SET
        size_bytes = EXCLUDED.size_bytes,
        sha256 = EXCLUDED.sha256,
        body = EXCLUDED.body,
        skipped_reason = EXCLUDED.skipped_reason
    WHERE turbotest.run_files.sha256 IS DISTINCT FROM EXCLUDED.sha256
       OR turbotest.run_files.skipped_reason IS DISTINCT FROM EXCLUDED.skipped_reason
    """
)


@dataclass(frozen=True)
class StoredFile:
    path: str
    size_bytes: int
    sha256: str
    body: bytes | None
    skipped_reason: str


@dataclass(frozen=True)
class _Job:
    session: PlatformSession
    workspace: Path | None
    insights: SessionInsights | None = None


@lru_cache(maxsize=1)
def machine() -> dict[str, Any]:
    """Железо этого компьютера: им подписаны графики ресурсов прогона."""
    memory = psutil.virtual_memory()
    return {
        "cpu_count": psutil.cpu_count() or 1,
        "ram_total_mb": round(memory.total / 1_048_576),
        "gpu_available": sys.platform == "win32",
    }


def read_manifest(config_path: str) -> dict[str, Any]:
    """config.json как он лежал в папке конфигурации в момент старта."""
    file = Path(config_path) / "config.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def collect_files(root: Path) -> list[StoredFile]:
    """Файлы рабочего каталога. Каталоги кэша и ссылки наружу не берём."""
    if not root.is_dir():
        return []
    base = root.resolve()
    found: list[StoredFile] = []
    for path in base.rglob("*"):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(base)
        except ValueError:
            continue
        if any(part in _SKIP_DIRS for part in relative.parts):
            continue
        try:
            size = path.stat().st_size
            posix = relative.as_posix()
            if size > MAX_FILE_BYTES:
                found.append(StoredFile(posix, size, f"skipped:{size}", None, "файл больше 2 МБ"))
                continue
            data = path.read_bytes()
        except OSError as exc:
            logger.warning("platform history skipped %s: %s", path, exc)
            continue
        found.append(StoredFile(posix, size, hashlib.sha256(data).hexdigest(), data, ""))
    found.sort(key=lambda item: item.path)
    return found


def _stamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def run_params(session: PlatformSession) -> dict[str, Any]:
    from app.platform.shared import author_name, host_name

    updated = _stamp(session.updated_at)
    return {
        "id": session.id,
        "config_id": session.config_id,
        "config_title": session.config_title,
        "source": session.source,
        "agent_id": session.agent_id,
        "agent_title": session.agent_title,
        "prompt": session.prompt,
        "status": session.status,
        "error": session.error,
        "sdk_agent_id": session.sdk_agent_id,
        "turns": session.turns,
        "model": session.model,
        "entry": list(session.entry),
        "config_manifest": session.config_manifest,
        "author": author_name(),
        "author_host": host_name(),
        "plan_turn": session.plan_turn,
        "plan": session.plan,
        "machine": machine(),
        "created_at": _stamp(session.created_at),
        "updated_at": updated,
        "finished_at": updated if session.status in _TERMINAL else None,
    }


def event_params(run_id: str, event: SessionEvent) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "seq": event.seq,
        "rev": event.rev,
        "turn": event.turn,
        "type": event.type,
        "body": event.text,
        "name": event.name,
        "status": event.status,
        "call_id": event.call_id,
        "args": event.args,
        "result": event.result,
        "args_chars": event.args_chars,
        "result_chars": event.result_chars,
        "label": event.label,
        "attachments": [item.model_dump() for item in event.attachments],
        "parent": event.parent,
    }


def insights_params(run_id: str, insights: SessionInsights) -> dict[str, Any]:
    body = gzip.compress(insights.model_dump_json().encode("utf-8"), compresslevel=6)
    return {"run_id": run_id, "body": body, "size_bytes": len(body)}


class HistoryWriter:
    def __init__(self, write: Callable[[_Job], None] | None = None, *, autostart: bool = True) -> None:
        self._write_job = write or self._write_db
        self._autostart = autostart
        self._lock = threading.Lock()
        self._pending: dict[str, _Job] = {}
        self._event = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._stop = False
        self._thread: threading.Thread | None = None
        self._engine: Engine | None = None
        self._schema_ready = False

    def submit(
        self, session: PlatformSession, workspace: Path | None, *, insights: SessionInsights | None = None
    ) -> None:
        if not settings.platform_history_enabled:
            return
        with self._lock:
            current = self._pending.get(session.id)
            if current is not None:
                workspace = workspace or current.workspace
                insights = insights or current.insights
            self._pending[session.id] = _Job(session, workspace, insights)
            self._idle.clear()
            self._event.set()
        if self._autostart:
            self._ensure_thread()

    def drain(self) -> None:
        with self._lock:
            batch = list(self._pending.values())
            self._pending.clear()
            if not batch:
                self._idle.set()
                return
        try:
            for job in batch:
                try:
                    self._write_job(job)
                except Exception:
                    logger.exception("platform history write failed for %s", job.session.id)
        finally:
            with self._lock:
                if not self._pending:
                    self._idle.set()

    def flush(self, timeout: float = 5.0) -> bool:
        if not settings.platform_history_enabled:
            return True
        return self._idle.wait(timeout)

    def close(self) -> None:
        self._stop = True
        self._event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2)

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._loop, name="platform-history", daemon=True)
            self._thread.start()

    def _loop(self) -> None:
        while not self._stop:
            self._event.wait()
            if self._stop:
                break
            with self._lock:
                self._event.clear()
            self.drain()

    def _engine_or_create(self) -> Engine:
        if self._engine is None:
            self._engine = create_engine(
                settings.constructor_database_url,
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
                pool_recycle=1800,
                future=True,
                connect_args={
                    "connect_timeout": settings.constructor_connect_timeout,
                    "options": "-c statement_timeout=15000",
                },
            )
        return self._engine

    def _write_db(self, job: _Job) -> None:
        last: SQLAlchemyError | None = None
        for attempt in range(3):
            try:
                self._write_once(job)
                return
            except SQLAlchemyError as exc:
                last = exc
                self._schema_ready = False
                time.sleep(0.4 * (attempt + 1))
        assert last is not None
        raise last

    def _write_once(self, job: _Job) -> None:
        session = job.session
        with self._engine_or_create().begin() as conn:
            if not self._schema_ready:
                for statement in _DDL:
                    conn.execute(text(statement))
            conn.execute(_UPSERT_RUN, run_params(session))
            if session.events:
                conn.execute(_UPSERT_EVENT, [event_params(session.id, event) for event in session.events])
            if job.workspace is not None:
                _sync_files(conn, session.id, collect_files(job.workspace))
            if job.insights is not None:
                conn.execute(_UPSERT_INSIGHTS, insights_params(session.id, job.insights))
        self._schema_ready = True

def _sync_files(conn: Any, run_id: str, files: list[StoredFile]) -> None:
    if not files:
        conn.execute(_DELETE_FILES, {"run_id": run_id})
        return
    conn.execute(_DELETE_OTHER_FILES, {"run_id": run_id, "paths": [item.path for item in files]})
    conn.execute(
        _UPSERT_FILE,
        [
            {
                "run_id": run_id,
                "path": item.path,
                "size_bytes": item.size_bytes,
                "sha256": item.sha256,
                "body": item.body,
                "skipped_reason": item.skipped_reason,
            }
            for item in files
        ],
    )


history = HistoryWriter()


# -- чтение: запуски всех компьютеров -----------------------------------------
@dataclass(frozen=True)
class RemoteRun:
    """Запуск из общей базы — для просмотра на любом компьютере."""

    session: PlatformSession
    insights: SessionInsights
    machine: dict[str, Any]
    author: str
    host: str


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, datetime) else str(value or "")


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return fallback
    return fallback if value is None else value


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def run_summary(row: dict[str, Any]) -> dict[str, Any]:
    """Строка turbotest.runs в форме PlatformSession.summary() плюс автор и компьютер."""
    return {
        "id": row["id"],
        "config_id": row["config_id"],
        "config_title": row["config_title"],
        "source": row["source"],
        "agent_id": row["agent_id"],
        "agent_title": row["agent_title"],
        "prompt": row["prompt"],
        "status": row["status"],
        "error": row["error"] or "",
        "sdk_agent_id": row["sdk_agent_id"] or "",
        "turns": int(row["turns"] or 0),
        "plan_turn": int(row["plan_turn"] or 0),
        "plan": "",
        "rev": 0,
        "model": row["model"] or "",
        "created_at": _iso(row["created_at"]),
        "updated_at": _iso(row["updated_at"]),
        "author": row["author"] or "",
        "author_host": row["author_host"] or "",
    }


def _event(row: dict[str, Any]) -> SessionEvent:
    files = _loads(row.get("attachments"), [])
    return SessionEvent(
        seq=row["seq"],
        rev=row["rev"],
        turn=row["turn"],
        type=row["type"],
        text=row["body"] or "",
        name=row["name"] or "",
        status=row["status"] or "",
        call_id=row["call_id"] or "",
        args=row["args"] or "",
        result=row["result"] or "",
        args_chars=row["args_chars"] or 0,
        result_chars=row["result_chars"] or 0,
        label=row.get("label") or "",
        parent=row.get("parent") or "",
        attachments=[Attachment.model_validate(item) for item in files if isinstance(item, dict)],
    )


class HistoryReader:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._engine: Engine | None = None
        self._schema_ready = False
        self._failed_at = 0.0
        self._error = ""
        self._list: tuple[float, int, list[dict[str, Any]]] | None = None
        self._runs: dict[str, tuple[float, RemoteRun]] = {}

    def reset(self) -> None:
        with self._lock:
            self._failed_at, self._error, self._list = 0.0, "", None
            self._runs.clear()

    def _connect(self) -> Any:
        if self._engine is None:
            self._engine = create_engine(
                settings.constructor_database_url,
                pool_pre_ping=True,
                pool_size=2,
                max_overflow=1,
                pool_recycle=1800,
                future=True,
                connect_args={
                    "connect_timeout": settings.constructor_connect_timeout,
                    "options": "-c statement_timeout=15000",
                },
            )
        return self._engine.begin()

    def _query(self, run: Callable[[Any], Any]) -> Any:
        """Запрос к базе с паузой после сбоя: «История» опрашивает список каждые несколько секунд."""
        with self._lock:
            if self._error and time.monotonic() - self._failed_at < RETRY_AFTER_SECONDS:
                raise RuntimeError(self._error)
        try:
            with self._connect() as conn:
                if not self._schema_ready:
                    for statement in _DDL:
                        conn.execute(text(statement))
                    self._schema_ready = True
                result = run(conn)
        except SQLAlchemyError as exc:
            message = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            with self._lock:
                self._failed_at = time.monotonic()
                self._error = f"История в общей базе недоступна: {message}"
                self._schema_ready = False
            raise RuntimeError(self._error) from exc
        with self._lock:
            self._error = ""
        return result

    def list_runs(self, limit: int = LIST_LIMIT) -> tuple[list[dict[str, Any]], str]:
        """Запуски всех компьютеров, новые сверху. Возвращает (items, ошибку)."""
        if not settings.platform_history_enabled:
            return [], ""
        with self._lock:
            cached = self._list
            if cached and cached[1] >= limit and time.monotonic() - cached[0] < LIST_CACHE_SECONDS:
                return cached[2][:limit], ""
        try:
            rows = self._query(lambda conn: [dict(r) for r in conn.execute(_LIST_RUNS, {"limit": limit}).mappings()])
        except RuntimeError as exc:
            return [], str(exc)
        items = [run_summary(row) for row in rows]
        with self._lock:
            self._list = (time.monotonic(), limit, items)
        return items, ""

    def load(self, run_id: str) -> RemoteRun | None:
        """Запуск целиком: диалог и статистика. None — нет в базе или база недоступна."""
        if not settings.platform_history_enabled or not _is_uuid(run_id):
            return None
        with self._lock:
            cached = self._runs.get(run_id)
            if cached:
                ttl = RUN_CACHE_SECONDS if cached[1].session.status in _TERMINAL else 3.0
                if time.monotonic() - cached[0] < ttl:
                    return cached[1]

        def read(conn: Any) -> RemoteRun | None:
            row = conn.execute(_ONE_RUN, {"id": run_id}).mappings().first()
            if row is None:
                return None
            events = [_event(dict(item)) for item in conn.execute(_RUN_EVENTS, {"id": run_id}).mappings()]
            blob = conn.execute(_RUN_INSIGHTS, {"id": run_id}).scalar()
            insights = SessionInsights()
            if blob:
                insights = SessionInsights.model_validate_json(gzip.decompress(bytes(blob)))
            summary = run_summary(dict(row))
            session = PlatformSession(
                **{key: summary[key] for key in PlatformSession.model_fields if key in summary and key not in ("rev", "plan")},
                rev=max((event.rev for event in events), default=0),
                plan=row["plan"] or "",
                entry=list(_loads(row["entry"], [])),
                events=events,
            )
            return RemoteRun(
                session=session,
                insights=insights,
                machine=dict(_loads(row["machine"], {})),
                author=summary["author"],
                host=summary["author_host"],
            )

        try:
            run = self._query(read)
        except (RuntimeError, ValueError, OSError) as exc:
            logger.warning("history run %s not loaded: %s", run_id, exc)
            return None
        if run is not None:
            with self._lock:
                self._runs[run_id] = (time.monotonic(), run)
                while len(self._runs) > RUN_CACHE_SIZE:
                    self._runs.pop(next(iter(self._runs)))
        return run

    def file(self, run_id: str, path: str) -> bytes | None:
        """Вложение сообщения из run_files. Только из attachments/ — остальное в просмотре не нужно."""
        parts = PurePosixPath(path).parts
        if not _is_uuid(run_id) or len(parts) < 2 or parts[0] != "attachments" or ".." in parts:
            return None
        try:
            body = self._query(lambda conn: conn.execute(_RUN_FILE, {"id": run_id, "path": path}).scalar())
        except RuntimeError:
            return None
        return bytes(body) if body else None


reader = HistoryReader()


def backfill() -> int:
    """Дозалить в базу запуски этого компьютера: новые, изменённые и записанные без статистики."""
    if not settings.platform_history_enabled:
        return 0
    sessions = [item for item in store.list(limit=100_000) if item.status in _TERMINAL and _is_uuid(item.id)]
    if not sessions:
        return 0
    try:
        rows = reader._query(
            lambda conn: [dict(r) for r in conn.execute(_SYNC_STATE, {"ids": [s.id for s in sessions]}).mappings()]
        )
    except RuntimeError as exc:
        logger.warning("history backfill skipped: %s", exc)
        return 0
    known = {row["id"]: row for row in rows}
    sent = 0
    for session in sessions:
        row = known.get(session.id)
        if row is not None and row["has_insights"] and row["author_host"]:
            stored = row["updated_at"]
            if isinstance(stored, datetime) and stored >= _stamp(session.updated_at):
                continue
        workspace = store.root / "workspaces" / session.id
        history.submit(
            session.model_copy(deep=True),
            workspace if workspace.is_dir() else None,
            insights=store.insights_copy(session.id),
        )
        sent += 1
    if sent:
        logger.info("history backfill: %s runs queued", sent)
    return sent


def start_backfill() -> None:
    if settings.platform_history_enabled:
        threading.Thread(target=backfill, name="platform-history-backfill", daemon=True).start()
