"""Задачи пользователя из SQL erp_pm (1С Task.ЗадачаИсполнителя)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Sequence

from app.clients import erp_sql
from app.clients.erp_sql import ErpOrgDept, ErpSqlError, ErpSubordinate, ErpUserProfile

_YEAR_OFFSET = 2000
_TASK_TABLES = ("dbo._Task39X1", "dbo._Task39")


class ErpTaskError(RuntimeError):
    pass


def from_1c_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.year >= 3000:
        try:
            return value.replace(year=value.year - _YEAR_OFFSET)
        except ValueError:
            return value - timedelta(days=365 * _YEAR_OFFSET)
    if value.year <= 2001:
        return None
    return value


def to_1c_datetime(value: datetime) -> datetime:
    if value.year >= 3000:
        return value
    try:
        return value.replace(year=value.year + _YEAR_OFFSET)
    except ValueError:
        return value + timedelta(days=365 * _YEAR_OFFSET)


def parse_date(raw: str, *, end: bool = False) -> datetime:
    text = (raw or "").strip()
    if not text:
        raise ErpTaskError("Нужна дата в формате YYYY-MM-DD")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            break
        except ValueError:
            parsed = None
    if parsed is None:
        raise ErpTaskError(f"Непонятная дата: {text}")
    if end and parsed.hour == 0 and parsed.minute == 0 and len(text) <= 10:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed


def _looks_like_1c_user_id(user_id: str) -> bool:
    """1С v8users.ID — hex без дефисов. UUID Constructor сюда не ходит."""
    text = (user_id or "").strip()
    if not text or "-" in text:
        return False
    return 16 <= len(text) <= 64 and all(ch in "0123456789abcdefABCDEF" for ch in text)


def resolve_actor(*, fio: str = "", user_id: str = "") -> tuple[str, str]:
    """Вернуть (fio, user_id) из явных аргументов, JWT или карточки erp_pm."""
    user_id = (user_id or "").strip()
    fio = (fio or "").strip()
    if user_id and _looks_like_1c_user_id(user_id):
        row = erp_sql.find_user_by_id(user_id)
        if row is not None:
            return row.fio or fio, row.id
    if fio:
        try:
            row = erp_sql.find_user_by_fio(fio)
            return row.fio, row.id
        except (erp_sql.UserNotFoundError, erp_sql.AmbiguousUserError):
            return fio, user_id
    raise ErpTaskError("Не удалось определить пользователя: нет ФИО в JWT и в аргументах")


def list_current_tasks(
    *,
    fio: str = "",
    user_id: str = "",
    limit: int = 50,
) -> dict[str, Any]:
    actor_fio, actor_id = resolve_actor(fio=fio, user_id=user_id)
    rows = _query_tasks(fio=actor_fio, only_open=True, limit=limit)
    return {
        "summary": f"Текущие задачи: {len(rows)} ({actor_fio})",
        "fio": actor_fio,
        "user_id": actor_id,
        "count": len(rows),
        "tasks": rows,
        "source": "erp_pm",
    }


def list_tasks_for_period(
    *,
    fio: str = "",
    user_id: str = "",
    date_from: str = "",
    date_to: str = "",
    include_done: bool = True,
    limit: int = 100,
) -> dict[str, Any]:
    actor_fio, actor_id = resolve_actor(fio=fio, user_id=user_id)
    start = parse_date(date_from)
    finish = parse_date(date_to, end=True)
    if finish < start:
        raise ErpTaskError("date_to раньше date_from")
    rows = _query_tasks(
        fio=actor_fio,
        only_open=not include_done,
        date_from=start,
        date_to=finish,
        limit=limit,
    )
    return {
        "summary": (
            f"Задачи {start.date().isoformat()}…{finish.date().isoformat()}: "
            f"{len(rows)} ({actor_fio})"
        ),
        "fio": actor_fio,
        "user_id": actor_id,
        "date_from": start.date().isoformat(),
        "date_to": finish.date().isoformat(),
        "count": len(rows),
        "tasks": rows,
        "source": "erp_pm",
    }


def _query_tasks(
    *,
    fio: str = "",
    fios: Sequence[str] | None = None,
    only_open: bool,
    limit: int = 50,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[dict[str, Any]]:
    names = [item.strip() for item in (*(fios or ()), fio) if item and item.strip()]
    unique_names: list[str] = []
    seen_names: set[str] = set()
    for name in names:
        if name in seen_names:
            continue
        seen_names.add(name)
        unique_names.append(name)
    if not unique_names:
        return []
    limit = max(1, min(int(limit or 50), 400))
    clauses = ["t._Marked = 0x00"]
    params: list[Any] = []
    if len(unique_names) == 1:
        clauses.append("LTRIM(RTRIM(u._Description)) = ?")
        params.append(unique_names[0])
    else:
        placeholders = ",".join("?" * len(unique_names))
        clauses.append(f"LTRIM(RTRIM(u._Description)) IN ({placeholders})")
        params.extend(unique_names)
    if only_open:
        clauses.append("t._Executed = 0x00")
    if date_from is not None:
        clauses.append("t._Date_Time >= ?")
        params.append(to_1c_datetime(date_from))
    if date_to is not None:
        clauses.append("t._Date_Time <= ?")
        params.append(to_1c_datetime(date_to))
    where = " AND ".join(clauses)
    sql_parts = [
        f"""
        SELECT
            CAST(t._Number AS nvarchar(32)) AS number,
            t._Date_Time AS created_raw,
            t._Fld2515 AS due_raw,
            t._Executed AS executed,
            CAST(t._Name AS nvarchar(500)) AS title,
            CAST(u._Description AS nvarchar(256)) AS performer
        FROM {table} t WITH (NOLOCK)
        INNER JOIN dbo._Reference366 u WITH (NOLOCK)
            ON t._Fld2503_RRRef = u._IDRRef
        WHERE {where}
        """
        for table in _TASK_TABLES
    ]
    inner = " UNION ALL ".join(sql_parts)
    sql = f"SELECT TOP ({limit}) * FROM ({inner}) AS tasks ORDER BY created_raw DESC"
    conn = erp_sql._connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(sql, params * len(_TASK_TABLES))
        columns = [col[0] for col in cur.description]
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in cur.fetchall():
            data = {columns[i]: row[i] for i in range(len(columns))}
            number = str(data.get("number") or "").strip()
            if number and number in seen:
                continue
            if number:
                seen.add(number)
            executed = data.get("executed")
            done = executed in (b"\x01", 1, True, "1")
            created = from_1c_datetime(data.get("created_raw"))
            due = from_1c_datetime(data.get("due_raw"))
            items.append(
                {
                    "number": number,
                    "title": " ".join(str(data.get("title") or "").split()),
                    "status": "выполнена" if done else "открыта",
                    "done": done,
                    "created_at": created.isoformat(sep=" ") if created else "",
                    "due_at": due.isoformat(sep=" ") if due else "",
                    "performer": str(data.get("performer") or "").strip(),
                }
            )
        return items
    except ErpSqlError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErpTaskError(f"Не удалось прочитать задачи из erp_pm: {exc}") from exc
    finally:
        conn.close()


def actor_from_args(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> tuple[str, str]:
    return (
        str(args.get("fio") or actor_fio or "").strip(),
        str(args.get("user_id") or args.get("userId") or actor_user_id or "").strip(),
    )


def actor_from_jwt(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> tuple[str, str]:
    """Identity from access_token argument or from the session JWT actor."""
    token = str(
        args.get("access_token") or args.get("jwt") or args.get("token") or ""
    ).strip()
    if token:
        from app.core.jwt import validate_token

        try:
            ctx = validate_token(token)
        except ValueError as exc:
            raise ErpTaskError("Недействительный JWT") from exc
        fio = (ctx.fio or "").strip()
        user_id = (ctx.user_id or "").strip()
        if not fio:
            raise ErpTaskError("В JWT нет ФИО")
        return fio, user_id
    fio, user_id = actor_from_args(
        {},
        actor_fio=actor_fio,
        actor_user_id=actor_user_id,
    )
    if not fio:
        raise ErpTaskError("Не удалось определить пользователя: нет ФИО в JWT")
    return fio, user_id


def _person_node(person: ErpSubordinate, tasks: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "fio": person.fio,
        "position": person.position,
        "department": person.department,
        "task_count": len(tasks),
        "tasks": tasks,
    }


def build_subordinate_task_tree(
    *,
    manager: ErpUserProfile,
    departments: list[ErpOrgDept],
    people: list[ErpSubordinate],
    tasks_by_fio: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Org tree: headed departments → people (position + tasks) → child departments."""
    by_parent: dict[str, list[ErpOrgDept]] = {}
    for dept in departments:
        if dept.is_root:
            continue
        by_parent.setdefault(dept.parent_id, []).append(dept)
    people_by_dept: dict[str, list[ErpSubordinate]] = {}
    leftovers: list[ErpSubordinate] = []
    dept_names = {item.name for item in departments}
    for person in people:
        if person.department in dept_names:
            people_by_dept.setdefault(person.department, []).append(person)
        else:
            leftovers.append(person)

    def render(dept: ErpOrgDept) -> dict[str, Any]:
        members = [
            _person_node(person, tasks_by_fio.get(person.fio, []))
            for person in people_by_dept.get(dept.name, [])
        ]
        children = [render(child) for child in by_parent.get(dept.id, [])]
        return {
            "department": dept.name,
            "people": members,
            "children": children,
        }

    tree = [render(dept) for dept in departments if dept.is_root]
    if leftovers:
        tree.append(
            {
                "department": "",
                "people": [
                    _person_node(person, tasks_by_fio.get(person.fio, []))
                    for person in leftovers
                ],
                "children": [],
            }
        )
    return tree


def list_subordinate_tasks(
    *,
    fio: str = "",
    user_id: str = "",
    only_open: bool = True,
    limit_per_person: int = 30,
) -> dict[str, Any]:
    actor_fio, actor_id = resolve_actor(fio=fio, user_id=user_id)
    try:
        manager, departments, people = erp_sql.load_subordinate_org(actor_fio)
    except ErpSqlError as exc:
        raise ErpTaskError(str(exc)) from exc
    if not manager.fio:
        manager = ErpUserProfile(fio=actor_fio)
    per_person = max(1, min(int(limit_per_person or 30), 100))
    tasks_by_fio: dict[str, list[dict[str, Any]]] = {person.fio: [] for person in people}
    if people:
        raw = _query_tasks(
            fios=[person.fio for person in people],
            only_open=only_open,
            limit=min(400, per_person * len(people)),
        )
        for task in raw:
            owner = str(task.get("performer") or "").strip()
            bucket = tasks_by_fio.get(owner)
            if bucket is None or len(bucket) >= per_person:
                continue
            bucket.append(task)
    tree = build_subordinate_task_tree(
        manager=manager,
        departments=departments,
        people=people,
        tasks_by_fio=tasks_by_fio,
    )
    task_count = sum(len(items) for items in tasks_by_fio.values())
    return {
        "summary": (
            f"Задачи подчинённых: {task_count} у {len(people)} чел. ({manager.fio or actor_fio})"
        ),
        "manager": {
            "fio": manager.fio or actor_fio,
            "position": manager.position,
            "department": manager.department,
            "user_id": actor_id,
        },
        "subordinate_count": len(people),
        "task_count": task_count,
        "tree": tree,
        "source": "erp_pm",
    }


def handle_current(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    fio, user_id = actor_from_args(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    return list_current_tasks(
        fio=fio,
        user_id=user_id,
        limit=int(args.get("limit") or 50),
    )


def handle_subordinate_tasks(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    fio, user_id = actor_from_jwt(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    include_done = args.get("include_done")
    only_open = True if include_done is None else not bool(include_done)
    if "only_open" in args:
        only_open = bool(args.get("only_open"))
    return list_subordinate_tasks(
        fio=fio,
        user_id=user_id,
        only_open=only_open,
        limit_per_person=int(args.get("limit_per_person") or args.get("limit") or 30),
    )


def handle_period(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    fio, user_id = actor_from_args(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    include_done = args.get("include_done")
    if include_done is None:
        include_done = True
    return list_tasks_for_period(
        fio=fio,
        user_id=user_id,
        date_from=str(args.get("date_from") or args.get("dateFrom") or ""),
        date_to=str(args.get("date_to") or args.get("dateTo") or ""),
        include_done=bool(include_done),
        limit=int(args.get("limit") or 100),
    )


def stub_current(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    fio, user_id = actor_from_args(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    fio = fio or "Пользователь"
    return {
        "summary": f"stub: текущие задачи ({fio})",
        "fio": fio,
        "user_id": user_id,
        "count": 0,
        "tasks": [],
        "source": "stub",
    }


def stub_subordinate_tasks(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    fio, user_id = actor_from_args(
        {},
        actor_fio=actor_fio,
        actor_user_id=actor_user_id,
    )
    token = str(args.get("access_token") or args.get("jwt") or args.get("token") or "").strip()
    if token:
        fio, user_id = actor_from_jwt(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    fio = fio or "Пользователь"
    return {
        "summary": f"stub: задачи подчинённых ({fio})",
        "manager": {
            "fio": fio,
            "position": "",
            "department": "",
            "user_id": user_id,
        },
        "subordinate_count": 0,
        "task_count": 0,
        "tree": [],
        "source": "stub",
    }


def stub_period(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    fio, user_id = actor_from_args(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    fio = fio or "Пользователь"
    return {
        "summary": f"stub: задачи за период ({fio})",
        "fio": fio,
        "user_id": user_id,
        "date_from": str(args.get("date_from") or args.get("dateFrom") or ""),
        "date_to": str(args.get("date_to") or args.get("dateTo") or ""),
        "count": 0,
        "tasks": [],
        "source": "stub",
    }

