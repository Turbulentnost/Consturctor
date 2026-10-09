"""Публикация агента платформы в базу оркестратора: public.workflows Constructor.

«Для всех» — одна запись автора библиотеки. Каталог оркестратора
(AgentLibraryGridTab) показывает только агентов, у владельца которых в ФИО есть
«Ильченко», поэтому публичная копия ставится этому пользователю.

«Выборочно» — копия тем пользователям, которые видны на странице входа
оркестратора (1С, «Показывать в списке выбора», GET /api/v1/auth/users?only_shown=true).
У копии стоит library_source_id, и каталог её не берёт: агент виден только
на доске выбранного пользователя.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any
from uuid import uuid4

import httpx
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Engine

from app.config import settings
from app.platform.sessions import PlatformAgent
from app.tools.constructor_session import ConstructorSessionError, access_token

# Каталог библиотеки оркестратора оставляет только агентов этого автора.
_LIBRARY_AUTHOR = "%ильченко%"
_LOGIN_LIMIT = 5000


class LibraryError(RuntimeError):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


_USERS = text(
    """
    SELECT id, btrim(fio) AS fio, btrim(position) AS position, btrim(department) AS department
    FROM users
    WHERE btrim(fio) <> ''
    """
)
_LIBRARY_AUTHORS = text(
    """
    SELECT id, btrim(fio) AS fio, btrim(position) AS position, btrim(department) AS department
    FROM users
    WHERE fio ILIKE :pattern AND btrim(fio) <> ''
    """
)
_FIND = text(
    """
    SELECT id, user_id
    FROM workflows
    WHERE notes = :notes
    ORDER BY updated_at DESC
    """
)
_INSERT_USER = text(
    """
    INSERT INTO users (
        id, fio, department, position, activity_status, is_support, created_at, updated_at
    ) VALUES (
        :id, :fio, :department, :position, 'online', false, :now, :now
    )
    ON CONFLICT (id) DO NOTHING
    """
)
_INSERT = text(
    """
    INSERT INTO workflows (
        id, user_id, title, phase, notes, document_name, document_text,
        plan_json, attachments_meta, local_run,
        plan_agent_id, plan_run_id, exec_agent_id, exec_run_id,
        last_result, branch, pr_url, created_at, updated_at
    ) VALUES (
        :id, :user_id, :title, 'done', :notes, '', '',
        CAST(:plan_json AS json), CAST('{}' AS json), CAST(:local_run AS json),
        '', '', '', '',
        '', '', '', :now, :now
    )
    """
)
_UPDATE = text(
    """
    UPDATE workflows SET
        user_id = :user_id,
        title = :title,
        phase = 'done',
        plan_json = CAST(:plan_json AS json),
        local_run = CAST(:local_run AS json),
        updated_at = :now
    WHERE id = :id
    """
)
_RETIRE = (
    text(
        """
        UPDATE workflows SET
            phase = 'deleted',
            local_run = CAST(
                jsonb_set(
                    CAST(COALESCE(local_run, CAST('{}' AS json)) AS jsonb),
                    '{deleted}',
                    CAST('true' AS jsonb),
                    true
                ) AS json
            ),
            updated_at = :now
        WHERE notes = :notes AND phase <> 'deleted' AND id NOT IN :keep
        """
    )
    .bindparams(bindparam("keep", expanding=True))
)


@lru_cache(maxsize=1)
def _engine() -> Engine:
    return create_engine(
        settings.constructor_database_url,
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=1,
        future=True,
        connect_args={"connect_timeout": settings.constructor_connect_timeout},
    )


def _mark(agent_id: str) -> str:
    return f"platform:{agent_id}"


def _erp_rank(user_id: str) -> int:
    """Настоящий id 1С — 32 hex. Тестовые копии вроде E11C4E11K… проигрывают."""
    token = user_id.strip().upper()
    if len(token) == 32 and all(char in "0123456789ABCDEF" for char in token):
        return 1
    return 0


def _prefer(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return max(rows, key=lambda row: (_erp_rank(str(row.get("id") or "")), str(row.get("id") or "")))


def _by_fio(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        fio = str(row.get("fio") or "").strip()
        if fio and str(row.get("id") or "").strip():
            grouped.setdefault(fio.casefold(), []).append(row)
    return {key: _prefer(items) for key, items in grouped.items()}


def _documents(agent: PlatformAgent, *, grant: str) -> tuple[str, str]:
    title = agent.title.strip() or "Без названия"
    instruction = agent.instruction.strip()
    plan = {
        "title": title,
        "goal": agent.request.strip(),
        "playbook": {"name": title, "instructions": instruction, "status": "verified"},
    }
    run: dict[str, Any] = {
        "published": True,
        "status": "published",
        "kind": "agent",
        "unformed": False,
        "deleted": False,
        "paused": False,
        "runtime": "cursor",
        "ui_mode": "chat",
        "playbook": {"name": title, "instructions": instruction, "status": "verified"},
    }
    # Копия «только этим людям» не должна снова попасть в общий каталог.
    if grant:
        run["library_source_id"] = grant
    return json.dumps(plan, ensure_ascii=False), json.dumps(run, ensure_ascii=False)


def _login_fios() -> list[str]:
    """Те же ФИО, что подсказка на странице входа оркестратора."""
    url = f"{settings.constructor_api_url.rstrip('/')}/api/v1/auth/users"
    try:
        response = httpx.get(
            url,
            params={"only_shown": "true", "limit": str(_LOGIN_LIMIT)},
            timeout=30.0,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise LibraryError(f"Список пользователей оркестратора недоступен: {exc}", status_code=502) from exc
    if response.status_code >= 400:
        raise LibraryError(
            f"Список пользователей оркестратора: HTTP {response.status_code}",
            status_code=502,
        )
    raw = response.json().get("items")
    if not isinstance(raw, list):
        raise LibraryError("Оркестратор вернул пустой список пользователей", status_code=502)
    names: list[str] = []
    seen: set[str] = set()
    for item in raw:
        fio = str(item or "").strip()
        key = fio.casefold()
        if fio and key not in seen:
            seen.add(key)
            names.append(fio)
    if not names:
        raise LibraryError("На странице входа оркестратора нет пользователей", status_code=502)
    return names


def list_login_users() -> list[dict[str, str]]:
    """Пользователи страницы входа. id пустой, если человек ещё не входил в оркестратор."""
    names = _login_fios()
    with _engine().connect() as conn:
        known = _by_fio([dict(row) for row in conn.execute(_USERS).mappings()])
    items: list[dict[str, str]] = []
    for fio in names:
        row = known.get(fio.casefold())
        items.append(
            {
                "id": str(row["id"]).strip() if row else "",
                "fio": fio,
                "position": str(row["position"] or "").strip() if row else "",
                "department": str(row["department"] or "").strip() if row else "",
            }
        )
    return items


def find_user(fio: str) -> dict[str, str] | None:
    """Пользователь оркестратора по ФИО: должность и подразделение из базы Constructor."""
    key = fio.strip().casefold()
    if not key:
        return None
    with _engine().connect() as conn:
        row = _by_fio([dict(row) for row in conn.execute(_USERS).mappings()]).get(key)
    if row is None:
        return None
    return {
        "fio": str(row["fio"] or "").strip(),
        "position": str(row["position"] or "").strip(),
        "department": str(row["department"] or "").strip(),
    }


def _directory_user(fio: str, token: str) -> dict[str, str]:
    url = f"{settings.constructor_api_url.rstrip('/')}/api/v1/auth/directory"
    try:
        response = httpx.get(
            url,
            params={"search": fio},
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
            trust_env=False,
        )
    except httpx.HTTPError as exc:
        raise LibraryError(f"Справочник оркестратора недоступен: {exc}", status_code=502) from exc
    if response.status_code in (401, 403):
        raise LibraryError("Оркестратор не принял сессию для справочника пользователей", status_code=502)
    if response.status_code >= 400:
        raise LibraryError(f"Справочник оркестратора: HTTP {response.status_code}", status_code=502)
    raw = response.json().get("items")
    exact = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = str(item.get("fio") or "").strip()
            user_id = str(item.get("id") or "").strip()
            if user_id and name.casefold() == fio.casefold():
                exact.append(item)
    if not exact:
        raise LibraryError(f"В 1С нет пользователя «{fio}»")
    picked = _prefer(
        [
            {
                "id": str(item.get("id") or "").strip(),
                "fio": str(item.get("fio") or "").strip(),
                "position": str(item.get("position") or "").strip(),
                "department": str(item.get("department") or "").strip(),
            }
            for item in exact
        ]
    )
    return picked


def _ensure_user(conn: Any, fio: str, known: dict[str, dict[str, Any]], token: str) -> str:
    row = known.get(fio.casefold())
    if row:
        return str(row["id"]).strip()
    if not token:
        try:
            token = access_token()
        except ConstructorSessionError as exc:
            raise LibraryError(str(exc), status_code=502) from exc
    found = _directory_user(fio, token)
    now = datetime.now(timezone.utc)
    conn.execute(
        _INSERT_USER,
        {
            "id": found["id"],
            "fio": found["fio"] or fio,
            "department": found["department"],
            "position": found["position"],
            "now": now,
        },
    )
    known[fio.casefold()] = found
    return found["id"]


def _library_owner(conn: Any, known: dict[str, dict[str, Any]]) -> str:
    authors = _by_fio([dict(row) for row in conn.execute(_LIBRARY_AUTHORS, {"pattern": _LIBRARY_AUTHOR}).mappings()])
    if authors:
        picked = _prefer(list(authors.values()))
        known[str(picked["fio"]).casefold()] = picked
        return str(picked["id"]).strip()
    for fio in _login_fios():
        if "ильченко" in fio.casefold():
            return _ensure_user(conn, fio, known, "")
    raise LibraryError(
        "В оркестраторе нет пользователя Ильченко — библиотека показывает только агентов этого автора"
    )


def _chosen_fios(raw: list[str]) -> list[str]:
    pending: list[str] = []
    for item in raw:
        fio = item.strip()
        if fio and fio.casefold() not in {name.casefold() for name in pending}:
            pending.append(fio)
    if not pending:
        raise LibraryError("Выберите хотя бы одного пользователя")
    allowed = {fio.casefold(): fio for fio in _login_fios()}
    chosen: list[str] = []
    unknown: list[str] = []
    for fio in pending:
        canonical = allowed.get(fio.casefold())
        if canonical is None:
            unknown.append(fio)
            continue
        if canonical not in chosen:
            chosen.append(canonical)
    if unknown:
        sample = ", ".join(unknown[:3])
        raise LibraryError(f"Этих пользователей нет на странице входа: {sample}")
    if not chosen:
        raise LibraryError("Выберите хотя бы одного пользователя")
    return chosen


def publish(agent: PlatformAgent, *, audience: str = "all", fios: list[str] | None = None) -> list[str]:
    """Поставить агента в библиотеку («all») или выдать копиями выбранным людям («selected»)."""
    if audience not in {"all", "selected"}:
        raise LibraryError("Неизвестный режим публикации")
    if not agent.instruction.strip():
        raise LibraryError("У агента нет инструкции")
    chosen = _chosen_fios(list(fios or [])) if audience == "selected" else []
    grant = _mark(agent.id) if audience == "selected" else ""
    plan_json, local_run = _documents(agent, grant=grant)
    now = datetime.now(timezone.utc)
    mark = _mark(agent.id)
    title = agent.title.strip() or "Без названия"
    with _engine().begin() as conn:
        known = _by_fio([dict(row) for row in conn.execute(_USERS).mappings()])
        token = ""
        if audience == "all":
            user_ids = [_library_owner(conn, known)]
        else:
            user_ids = []
            for fio in chosen:
                if not token and fio.casefold() not in known:
                    try:
                        token = access_token()
                    except ConstructorSessionError as exc:
                        raise LibraryError(
                            f"Пользователя «{fio}» ещё нет в базе оркестратора, "
                            f"а получить его id из 1С не удалось: {exc}",
                            status_code=502,
                        ) from exc
                user_ids.append(_ensure_user(conn, fio, known, token))
        existing: dict[str, list[str]] = {}
        for row in conn.execute(_FIND, {"notes": mark}).mappings():
            existing.setdefault(str(row["user_id"]), []).append(str(row["id"]))
        kept: list[str] = []
        for user_id in dict.fromkeys(user_ids):
            payload = {
                "user_id": user_id,
                "title": title,
                "notes": mark,
                "plan_json": plan_json,
                "local_run": local_run,
                "now": now,
            }
            rows = existing.get(user_id) or []
            if rows:
                conn.execute(_UPDATE, {**payload, "id": rows[0]})
                kept.append(rows[0])
            else:
                workflow_id = str(uuid4())
                conn.execute(_INSERT, {**payload, "id": workflow_id})
                kept.append(workflow_id)
        if kept:
            conn.execute(_RETIRE, {"now": now, "notes": mark, "keep": kept})
    return kept
