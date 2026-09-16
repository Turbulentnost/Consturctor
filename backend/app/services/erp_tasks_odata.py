"""Текущие задачи erp_pm через OData Task_ЗадачаИсполнителя (+ опционально SQL merge)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.erp_assignments import TASK_ENTITY, AssignmentError, resolve_user
from app.services.erp_tasks import (
    ErpTaskError,
    actor_from_args,
    from_1c_datetime,
    merge_task_lists,
    resolve_actor,
    task_is_late,
    _query_tasks,
)
_USER_TASK_FIELDS = (
    "Description",
    "ПредметСтрокой",
    "РезультатВыполнения",
    "Комментарий",
)


def _parse_odata_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return from_1c_datetime(value) or value
    text = str(value).strip()
    if not text or text.startswith("0001-01-01"):
        return None
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def _performer_name(row: dict[str, Any]) -> str:
    for key in ("Исполнитель_Name", "Исполнитель"):
        value = row.get(key)
        text = str(value or "").strip()
        if text and "@" not in key and not text.startswith("00000000-"):
            return text
    return ""


def _map_odata_task_row(row: dict[str, Any]) -> dict[str, Any]:
    done = bool(row.get("Executed"))
    created = _parse_odata_datetime(row.get("Date"))
    due = _parse_odata_datetime(
        row.get("СрокИсполнения") or row.get("Срок") or row.get("Date")
    )
    completed = _parse_odata_datetime(
        row.get("DateИсполнения") or row.get("ДатаИсполнения") or row.get("ДатаЗавершения")
    )
    if done and completed is None:
        completed = created
    late = task_is_late(done=done, completed_at=completed, due_at=due)
    exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    title = " ".join(
        str(row.get("Description") or row.get("Subject") or row.get("Наименование") or "").split()
    )
    comment = " ".join(
        str(
            row.get("РезультатВыполнения")
            or row.get("Комментарий")
            or row.get("ПредметСтрокой")
            or ""
        ).split()
    )
    number = str(row.get("Number") or row.get("Code") or "").strip()
    mapped = {
        "number": number,
        "title": title,
        "status": "выполнена" if done else "открыта",
        "done": done,
        "late": late,
        "created_at": created.isoformat(sep=" ") if created else "",
        "due_at": due.isoformat(sep=" ") if due else "",
        "completed_at": completed.isoformat(sep=" ") if completed else "",
        "comment": comment,
        "approval": "завершена" if done else "не согласовано",
        "exported_at": exported_at,
        "performer": _performer_name(row),
        "source": "erp_pm+odata",
        "ref_key": str(row.get("Ref_Key") or "").strip(),
    }
    return mapped


def _row_mentions_fio(row: dict[str, Any], fio: str) -> bool:
    needle = " ".join(str(fio or "").split()).casefold()
    if not needle:
        return False
    parts = [part for part in needle.split() if len(part) >= 3]
    blob = " ".join(
        str(row.get(field) or "") for field in _USER_TASK_FIELDS
    ).casefold()
    if needle in blob:
        return True
    return any(part in blob for part in parts)


def _fetch_odata_tasks(
    *,
    fio: str,
    limit: int,
    auth_args: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], str]:
    """OData МоиЗадачи: мне (Исполнитель) + от меня (Автор) + ФИО в теме."""
    from app.services.erp_task_odata_scan import (
        ROLE_AUTHOR,
        ROLE_EXECUTOR,
        ROLE_MENTION,
        scan_task_zadacha_ispolnitelya,
    )
    from app.services.onec_tools import OnecToolError, _fetch_odata_list, odata_configured

    if not odata_configured(auth_args):
        raise ErpTaskError(
            "OData erp_pm не настроен: нужны ODATA_BASE_URL и "
            "ODATA_USERNAME/ODATA_PASSWORD или ERP_LOGIN/ERP_PASSWORD "
            "(backend/.env или odata_* в invoke)"
        )
    top = max(1, min(int(limit or 50), 200))
    warnings: list[str] = []

    try:
        user = resolve_user(fio)
    except AssignmentError as exc:
        raise ErpTaskError(str(exc)) from exc

    def fetch_page(_entity: str, *, params: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "entity": TASK_ENTITY,
            "top": int(params.get("$top") or top),
            "skip": int(params.get("$skip") or 0),
            "filter": str(params.get("$filter") or ""),
        }
        if auth_args:
            payload.update(auth_args)
        return _fetch_odata_list(payload)

    def map_row(row: dict[str, Any], role: str) -> dict[str, Any]:
        mapped = _map_odata_task_row(row)
        if role == ROLE_AUTHOR:
            mapped["source"] = "erp_pm+odata (от меня)"
        return mapped

    try:
        scanned, scan_warning = scan_task_zadacha_ispolnitelya(
            user_ref=user["ref_key"],
            fio=fio,
            limit=top,
            fetch_page=fetch_page,
            mention_checker=_row_mentions_fio,
            map_row=map_row,
            roles=frozenset({ROLE_EXECUTOR, ROLE_AUTHOR, ROLE_MENTION}),
        )
    except OnecToolError as exc:
        raise ErpTaskError(f"OData Task_ЗадачаИсполнителя: {exc}") from exc

    if scan_warning:
        warnings.append(scan_warning)

    deduped = merge_task_lists([], scanned, limit=top)
    return deduped, " · ".join(w for w in warnings if w)


def list_current_tasks_odata(
    *,
    fio: str = "",
    user_id: str = "",
    limit: int = 50,
    auth_args: dict[str, Any] | None = None,
    fallback_sql: bool = True,
) -> dict[str, Any]:
    actor_fio, actor_id = resolve_actor(fio=fio, user_id=user_id)
    limit = max(1, min(int(limit or 50), 200))
    odata_warning = ""
    tasks: list[dict[str, Any]] = []
    try:
        tasks, odata_warning = _fetch_odata_tasks(
            fio=actor_fio,
            limit=limit,
            auth_args=auth_args,
        )
    except ErpTaskError as exc:
        odata_warning = str(exc)

    sql_fallback_count = 0
    if fallback_sql:
        try:
            sql_rows = _query_tasks(fio=actor_fio, only_open=True, limit=limit)
            before = len(tasks)
            tasks = merge_task_lists(tasks, sql_rows, limit=limit)
            sql_fallback_count = max(0, len(tasks) - before)
        except ErpTaskError as exc:
            if not tasks:
                raise
            odata_warning = " · ".join(
                part for part in (odata_warning, f"SQL fallback: {exc}") if part
            )

    merged = {actor_fio: tasks}
    docflow_warning = ""
    try:
        from app.services.erp_tasks import _attach_docflow

        docflow_warning = _attach_docflow(
            merged,
            date_from=None,
            date_to=None,
            only_open=True,
            limit_per_person=limit,
            auth_args=auth_args,
        )
    except Exception as exc:  # noqa: BLE001 — docflow must not hide erp_pm OData tasks
        docflow_warning = str(exc).strip() or "Документооборот: ошибка слияния"
    tasks = merged[actor_fio]
    source = "erp_pm+odata+документооборот" if docflow_warning or any(
        str(t.get("source") or "").startswith("документооборот") for t in tasks
    ) else "erp_pm+odata"

    return {
        "summary": f"Текущие задачи (OData): {len(tasks)} ({actor_fio})",
        "fio": actor_fio,
        "user_id": actor_id,
        "count": len(tasks),
        "tasks": tasks,
        "source": source,
        "odata_warning": odata_warning,
        "sql_fallback_merged": sql_fallback_count,
        "docflow_warning": docflow_warning,
    }


def handle_odata_current(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    fio, user_id = actor_from_args(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    fallback_sql = args.get("fallback_sql")
    if fallback_sql is None:
        fallback_sql = args.get("fallbackSql")
    if fallback_sql is None:
        fallback_sql = True
    return list_current_tasks_odata(
        fio=fio,
        user_id=user_id,
        limit=int(args.get("limit") or 50),
        auth_args=args,
        fallback_sql=bool(fallback_sql),
    )


def stub_odata_current(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    fio, user_id = actor_from_args(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    fio = fio or "Пользователь"
    return {
        "summary": f"stub: OData задачи ({fio})",
        "fio": fio,
        "user_id": user_id,
        "count": 0,
        "tasks": [],
        "source": "stub",
        "odata_warning": "OData erp_pm не настроен на backend",
        "sql_fallback_merged": 0,
        "docflow_warning": "",
    }
