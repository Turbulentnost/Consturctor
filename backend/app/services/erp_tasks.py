"""Задачи пользователя из SQL erp_pm (1С Task.ЗадачаИсполнителя)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
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


def task_is_late(
    *,
    done: bool,
    completed_at: datetime | None,
    due_at: datetime | None,
) -> bool:
    if not done or completed_at is None or due_at is None:
        return False
    return completed_at > due_at


def earliest_task_date() -> date | None:
    sql = """
    SELECT MIN(created_raw) AS created_raw
    FROM (
        SELECT MIN(t._Date_Time) AS created_raw
        FROM dbo._Task39X1 t WITH (NOLOCK)
        WHERE t._Marked = 0x00 AND t._Date_Time > '2001-01-02'
        UNION ALL
        SELECT MIN(t._Date_Time)
        FROM dbo._Task39 t WITH (NOLOCK)
        WHERE t._Marked = 0x00 AND t._Date_Time > '2001-01-02'
    ) AS span
    """
    conn = erp_sql._connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(sql)
        row = cur.fetchone()
        raw = row[0] if row else None
        converted = from_1c_datetime(raw) if isinstance(raw, datetime) else None
        return converted.date() if converted else None
    except Exception:  # noqa: BLE001
        return None
    finally:
        conn.close()


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
    merged = {actor_fio: rows}
    warning = _attach_docflow(
        merged,
        date_from=None,
        date_to=None,
        only_open=True,
        limit_per_person=limit,
    )
    rows = merged[actor_fio]
    return {
        "summary": f"Текущие задачи: {len(rows)} ({actor_fio})",
        "fio": actor_fio,
        "user_id": actor_id,
        "count": len(rows),
        "tasks": rows,
        "source": "erp_pm+документооборот",
        "docflow_warning": warning,
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
    merged = {actor_fio: rows}
    warning = _attach_docflow(
        merged,
        date_from=start,
        date_to=finish,
        only_open=not include_done,
        limit_per_person=limit,
    )
    rows = merged[actor_fio]
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
        "source": "erp_pm+документооборот",
        "docflow_warning": warning,
    }


def _query_tasks(
    *,
    fio: str = "",
    fios: Sequence[str] | None = None,
    only_open: bool,
    limit: int = 50,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    match_due: bool = False,
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
    limit = max(1, min(int(limit or 50), 2000))
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
    if date_from is not None and date_to is not None and match_due:
        clauses.append(
            "("
            "(t._Date_Time >= ? AND t._Date_Time <= ?)"
            " OR (t._Fld2515 > '2001-01-02' AND t._Fld2515 >= ? AND t._Fld2515 <= ?)"
            ")"
        )
        start_1c = to_1c_datetime(date_from)
        finish_1c = to_1c_datetime(date_to)
        params.extend([start_1c, finish_1c, start_1c, finish_1c])
    else:
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
            t._Fld2506 AS completed_raw,
            t._Executed AS executed,
            CAST(t._Name AS nvarchar(500)) AS title,
            CAST(t._Fld2509 AS nvarchar(1000)) AS comment,
            CAST(t._Fld2513 AS nvarchar(300)) AS approval,
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
        exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
            completed = from_1c_datetime(data.get("completed_raw"))
            comment = " ".join(str(data.get("comment") or "").split())
            approval = " ".join(str(data.get("approval") or "").split())
            late = task_is_late(done=done, completed_at=completed, due_at=due)
            items.append(
                {
                    "number": number,
                    "title": " ".join(str(data.get("title") or "").split()),
                    "status": "выполнена" if done else "открыта",
                    "done": done,
                    "late": late,
                    "created_at": created.isoformat(sep=" ") if created else "",
                    "due_at": due.isoformat(sep=" ") if due else "",
                    "completed_at": completed.isoformat(sep=" ") if completed else "",
                    "comment": comment,
                    "approval": approval or ("завершена" if done else "не согласовано"),
                    "exported_at": exported_at,
                    "performer": str(data.get("performer") or "").strip(),
                    "source": "erp_pm",
                }
            )
        return items
    except ErpSqlError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ErpTaskError(f"Не удалось прочитать задачи из erp_pm: {exc}") from exc
    finally:
        conn.close()


def merge_task_lists(
    existing: list[dict[str, Any]],
    extra: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    def key(task: dict[str, Any]) -> str:
        number = str(task.get("number") or "").strip()
        source = str(task.get("source") or "").strip()
        if number:
            return f"{source}:{number}"
        return f"{source}:{task.get('title')}|{task.get('due_at')}"

    seen = {key(item) for item in existing}
    out = list(existing)
    for item in extra:
        marker = key(item)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
        if len(out) >= limit:
            break
    return out


def _attach_docflow(
    tasks_by_fio: dict[str, list[dict[str, Any]]],
    *,
    date_from: datetime | None,
    date_to: datetime | None,
    only_open: bool,
    limit_per_person: int,
) -> str:
    from app.services.docflow_tasks import list_docflow_for_people

    extra, warning = list_docflow_for_people(
        list(tasks_by_fio),
        date_from=date_from,
        date_to=date_to,
        only_open=only_open,
        limit_per_person=limit_per_person,
    )
    for name, items in extra.items():
        bucket = tasks_by_fio.setdefault(name, [])
        tasks_by_fio[name] = merge_task_lists(bucket, items, limit=limit_per_person)
    return warning


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


def _person_node(
    person: ErpSubordinate,
    tasks: list[dict[str, Any]],
    *,
    level: int,
    subordinates: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "fio": person.fio,
        "position": person.position,
        "department": person.department,
        "level": level,
        "task_count": len(tasks),
        "tasks": tasks,
        "subordinates": subordinates,
    }


def _direct_reports(
    manager_fio: str,
    *,
    departments: list[ErpOrgDept],
    people: list[ErpSubordinate],
    person_by_fio: dict[str, ErpSubordinate],
) -> list[ErpSubordinate]:
    headed = [dept for dept in departments if dept.head_fio == manager_fio]
    if not headed:
        return []
    headed_ids = {dept.id for dept in headed}
    headed_names = {dept.name for dept in headed}
    head_fios = {dept.head_fio for dept in departments if dept.head_fio}
    result: list[ErpSubordinate] = []
    seen = {manager_fio}
    for dept in departments:
        head = dept.head_fio
        if dept.parent_id not in headed_ids or not head or head in seen:
            continue
        seen.add(head)
        result.append(
            person_by_fio.get(head)
            or ErpSubordinate(fio=head, position="", department=dept.name)
        )
    for person in people:
        if person.fio in seen:
            continue
        if person.department in headed_names and person.fio not in head_fios:
            seen.add(person.fio)
            result.append(person)
    return result


def build_subordinate_task_tree(
    *,
    manager: ErpUserProfile,
    departments: list[ErpOrgDept],
    people: list[ErpSubordinate],
    tasks_by_fio: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Person tree: direct reports first, then their reports, and so on."""
    person_by_fio = {person.fio: person for person in people}
    for dept in departments:
        if dept.head_fio and dept.head_fio not in person_by_fio:
            person_by_fio[dept.head_fio] = ErpSubordinate(
                fio=dept.head_fio,
                position="",
                department=dept.name,
            )

    def render(person: ErpSubordinate, level: int, trail: frozenset[str]) -> dict[str, Any]:
        if person.fio in trail or level > 8:
            return _person_node(
                person,
                tasks_by_fio.get(person.fio, []),
                level=level,
                subordinates=[],
            )
        kids = _direct_reports(
            person.fio,
            departments=departments,
            people=people,
            person_by_fio=person_by_fio,
        )
        return _person_node(
            person,
            tasks_by_fio.get(person.fio, []),
            level=level,
            subordinates=[
                render(child, level + 1, trail | {person.fio}) for child in kids
            ],
        )

    roots = _direct_reports(
        manager.fio,
        departments=departments,
        people=people,
        person_by_fio=person_by_fio,
    )
    return [render(person, 1, frozenset({manager.fio})) for person in roots]


def _count_tree_people(nodes: list[dict[str, Any]]) -> int:
    total = 0
    for node in nodes:
        total += 1
        total += _count_tree_people(list(node.get("subordinates") or []))
    return total


def list_subordinate_tasks(
    *,
    fio: str = "",
    user_id: str = "",
    only_open: bool = False,
    limit_per_person: int = 30,
    date_from: str = "",
    date_to: str = "",
    full_range: bool = False,
    include_self: bool = True,
) -> dict[str, Any]:
    actor_fio, actor_id = resolve_actor(fio=fio, user_id=user_id)
    try:
        manager, departments, people = erp_sql.load_subordinate_org(actor_fio)
    except ErpSqlError as exc:
        raise ErpTaskError(str(exc)) from exc
    if not manager.fio:
        manager = ErpUserProfile(fio=actor_fio)
    erp_since = earliest_task_date()
    start = parse_date(date_from) if (date_from or "").strip() else None
    finish = parse_date(date_to, end=True) if (date_to or "").strip() else None
    if start and finish and finish < start:
        raise ErpTaskError("date_to раньше date_from")
    if start is None or finish is None:
        today = date.today()
        finish = datetime.combine(today, datetime.max.time()).replace(microsecond=0)
        if full_range and erp_since is not None:
            start = datetime.combine(erp_since, datetime.min.time())
        else:
            start = datetime.combine(today - timedelta(days=30), datetime.min.time())
    per_person = max(1, min(int(limit_per_person or 30), 200))
    fios = [person.fio for person in people]
    manager_fio = manager.fio or actor_fio
    if include_self and manager_fio and manager_fio not in fios:
        fios.append(manager_fio)
    for dept in departments:
        if dept.head_fio and dept.head_fio != manager_fio and dept.head_fio not in fios:
            fios.append(dept.head_fio)
    tasks_by_fio: dict[str, list[dict[str, Any]]] = {name: [] for name in fios}
    if fios:
        raw = _query_tasks(
            fios=fios,
            only_open=only_open,
            date_from=start,
            date_to=finish,
            match_due=True,
            limit=min(2000, per_person * len(fios)),
        )
        for task in raw:
            owner = str(task.get("performer") or "").strip()
            bucket = tasks_by_fio.get(owner)
            if bucket is None or len(bucket) >= per_person:
                continue
            bucket.append(task)
    warning = _attach_docflow(
        tasks_by_fio,
        date_from=start,
        date_to=finish,
        only_open=only_open,
        limit_per_person=per_person,
    )
    tree = build_subordinate_task_tree(
        manager=manager,
        departments=departments,
        people=people,
        tasks_by_fio=tasks_by_fio,
    )
    if include_self and manager_fio:
        self_node = _person_node(
            ErpSubordinate(
                fio=manager_fio,
                position=manager.position,
                department=manager.department,
            ),
            tasks_by_fio.get(manager_fio, []),
            level=0,
            subordinates=[],
        )
        tree = [self_node, *tree]
    task_count = sum(len(items) for items in tasks_by_fio.values())
    period_from = start.date().isoformat()
    period_to = finish.date().isoformat()
    people_count = _count_tree_people(tree)
    return {
        "summary": (
            f"Задачи {period_from}…{period_to}: "
            f"{task_count} у {people_count} чел. ({manager_fio})"
        ),
        "manager": {
            "fio": manager_fio,
            "position": manager.position,
            "department": manager.department,
            "user_id": actor_id,
        },
        "date_from": period_from,
        "date_to": period_to,
        "erp_since": erp_since.isoformat() if erp_since else "",
        "subordinate_count": people_count,
        "task_count": task_count,
        "tree": tree,
        "source": "erp_pm+документооборот",
        "docflow_warning": warning,
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
    only_open = False if include_done is None else not bool(include_done)
    if "only_open" in args:
        only_open = bool(args.get("only_open"))
    include_self = args.get("include_self")
    if include_self is None:
        include_self = args.get("includeSelf")
    if include_self is None:
        include_self = True
    return list_subordinate_tasks(
        fio=fio,
        user_id=user_id,
        only_open=only_open,
        limit_per_person=int(args.get("limit_per_person") or args.get("limit") or 30),
        date_from=str(args.get("date_from") or args.get("dateFrom") or ""),
        date_to=str(args.get("date_to") or args.get("dateTo") or ""),
        full_range=bool(args.get("full_range") or args.get("fullRange")),
        include_self=bool(include_self),
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
        "date_from": str(args.get("date_from") or args.get("dateFrom") or ""),
        "date_to": str(args.get("date_to") or args.get("dateTo") or ""),
        "erp_since": "",
        "tree": [],
        "source": "stub",
        "docflow_warning": "",
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

