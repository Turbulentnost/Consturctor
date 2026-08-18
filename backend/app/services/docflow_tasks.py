"""Задачи 1С:Документооборот (публикация /doc) через OData."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.services.erp_tasks import from_1c_datetime, task_is_late

_TASK_ENTITY = "Task_ЗадачаИсполнителя"
_USER_ENTITY = "Catalog_Пользователи"


class DocflowError(RuntimeError):
    pass


def docflow_base_url() -> str:
    explicit = settings.docflow_odata_base_url.strip()
    if explicit:
        return explicit.rstrip("/")
    erp = settings.odata_base_url.strip()
    if "/erp_pm/" in erp:
        return erp.replace("/erp_pm/", "/doc/").rstrip("/")
    return ""


def docflow_auth() -> tuple[str, str] | None:
    user = (settings.docflow_odata_username or settings.odata_username or settings.erp_login).strip()
    password = (
        settings.docflow_odata_password or settings.odata_password or settings.erp_password
    ).strip()
    if user and password:
        return user, password
    return None


def docflow_configured() -> bool:
    return bool(docflow_base_url() and docflow_auth())


def _odata_str(value: str) -> str:
    return (value or "").replace("'", "''")


def _odata_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    base = docflow_base_url()
    auth = docflow_auth()
    if not base or not auth:
        raise DocflowError("OData документооборота не настроен")
    url = f"{base}/{path.lstrip('/')}"
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.get(url, params=params, headers={"Accept": "application/json"})
    if response.status_code in {401, 402}:
        raise DocflowError(
            "Документооборот (/doc) отклонил учётку OData. "
            "Добавьте того же пользователя в базу 1С:Документооборот "
            "или задайте DOCFLOW_ODATA_USERNAME / DOCFLOW_ODATA_PASSWORD."
        )
    if response.status_code >= 400:
        text = response.text.lstrip("\ufeff")[:280].replace("\n", " ")
        raise DocflowError(f"Документооборот OData HTTP {response.status_code}: {text}")
    data = response.json()
    return data if isinstance(data, dict) else {}


def find_user_key(fio: str) -> str:
    name = _odata_str(fio.strip())
    if not name:
        return ""
    data = _get(_USER_ENTITY, params={"$top": 5, "$filter": f"Description eq '{name}'"})
    for row in data.get("value") or []:
        if isinstance(row, dict) and row.get("Ref_Key"):
            return str(row["Ref_Key"])
    return ""


def _parse_odata_dt(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text or text.startswith("0001-01-01"):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", ""))
    except ValueError:
        return None
    return from_1c_datetime(parsed) or parsed


def _map_task(row: dict[str, Any], *, fio: str) -> dict[str, Any]:
    done = bool(row.get("Executed"))
    created = _parse_odata_dt(row.get("Date"))
    due = _parse_odata_dt(row.get("СрокИсполнения"))
    completed = _parse_odata_dt(row.get("ДатаИсполнения"))
    comment = " ".join(str(row.get("Описание") or row.get("РезультатВыполнения") or "").split())
    approval = str(row.get("СостояниеБизнесПроцесса") or "").strip()
    title = " ".join(str(row.get("Description") or row.get("ПредметСтрокой") or "").split())
    return {
        "number": str(row.get("Number") or "").strip(),
        "title": title,
        "status": "выполнена" if done else "открыта",
        "done": done,
        "late": task_is_late(done=done, completed_at=completed, due_at=due),
        "created_at": created.isoformat(sep=" ") if created else "",
        "due_at": due.isoformat(sep=" ") if due else "",
        "completed_at": completed.isoformat(sep=" ") if completed else "",
        "comment": comment,
        "approval": approval or ("завершена" if done else "не согласовано"),
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "performer": fio,
        "source": "документооборот",
    }


def list_docflow_tasks(
    *,
    fio: str,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    only_open: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if not docflow_configured():
        return []
    user_key = find_user_key(fio)
    if not user_key:
        return []
    limit = max(1, min(int(limit or 200), 200))
    clauses = [
        f"Исполнитель eq cast(guid'{user_key}','Catalog_Пользователи')",
    ]
    if only_open:
        clauses.append("Executed eq false")
    if date_from is not None:
        clauses.append(f"Date ge datetime'{_odata_dt(date_from)}'")
    if date_to is not None:
        clauses.append(f"Date le datetime'{_odata_dt(date_to)}'")
    filt = " and ".join(clauses)
    data = _get(
        _TASK_ENTITY,
        params={"$top": limit, "$orderby": "Date desc", "$filter": filt},
    )
    items: list[dict[str, Any]] = []
    for row in data.get("value") or []:
        if isinstance(row, dict):
            items.append(_map_task(row, fio=fio))
    return items


def list_docflow_for_people(
    fios: list[str],
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    only_open: bool = False,
    limit_per_person: int = 200,
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    warning = ""
    result: dict[str, list[dict[str, Any]]] = {name: [] for name in fios}
    if not docflow_configured():
        return result, "Документооборот: нет URL/учётки OData"
    try:
        for name in fios:
            if not name:
                continue
            result[name] = list_docflow_tasks(
                fio=name,
                date_from=date_from,
                date_to=date_to,
                only_open=only_open,
                limit=limit_per_person,
            )
    except DocflowError as exc:
        return {name: [] for name in fios}, str(exc)
    return result, warning


def handle_docflow_tasks(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    from app.services.erp_tasks import actor_from_jwt, parse_date

    fio, user_id = actor_from_jwt(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    date_from_raw = str(args.get("date_from") or args.get("dateFrom") or "").strip()
    date_to_raw = str(args.get("date_to") or args.get("dateTo") or "").strip()
    start = parse_date(date_from_raw) if date_from_raw else None
    finish = parse_date(date_to_raw, end=True) if date_to_raw else None
    include_done = args.get("include_done")
    only_open = True if include_done is None else not bool(include_done)
    if "only_open" in args:
        only_open = bool(args.get("only_open"))
    warning = ""
    try:
        tasks = list_docflow_tasks(
            fio=fio,
            date_from=start,
            date_to=finish,
            only_open=only_open,
            limit=int(args.get("limit") or 200),
        )
    except DocflowError as exc:
        tasks = []
        warning = str(exc)
    return {
        "summary": f"Задачи документооборота: {len(tasks)} ({fio})",
        "fio": fio,
        "user_id": user_id,
        "count": len(tasks),
        "tasks": tasks,
        "source": "документооборот",
        "docflow_warning": warning,
    }


def stub_docflow_tasks(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    from app.services.erp_tasks import actor_from_args, actor_from_jwt

    fio, user_id = actor_from_args({}, actor_fio=actor_fio, actor_user_id=actor_user_id)
    token = str(args.get("access_token") or args.get("jwt") or args.get("token") or "").strip()
    if token:
        fio, user_id = actor_from_jwt(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
    fio = fio or "Пользователь"
    return {
        "summary": f"stub: задачи документооборота ({fio})",
        "fio": fio,
        "user_id": user_id,
        "count": 0,
        "tasks": [],
        "source": "stub",
        "docflow_warning": "",
    }
