"""Поручения ERP: Документ.ТД_Поручения через OData erp_pm."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
import re

import httpx

from app.config import (
    odata_auth,
    odata_base_url,
    odata_timeout_sec,
    regagent_test_fio,
    regagent_test_login_enabled,
)
from app.services.erp_task_utils import ErpTaskError, from_1c_datetime, parse_date

_DOC_ENTITY = "Document_ТД_Поручения"
_USER_ENTITY = "Catalog_Пользователи"
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_CANCELLED = "отменено"

URGENCY_COLORS: dict[str, str] = {
    "overdue": "#FECACA",       # пастельный красный — просрочено
    "due_soon": "#FFE0B2",      # пастельный оранжевый — ≤1 день
    "due_3days": "#FFF9C4",     # пастельный жёлтый — 2–3 дня
    "accepted": "#D4EDDA",      # пастельный зелёный — принято
    "none": "#F3F4F6",          # нейтральный
    "done_ok": "#E5E7EB",       # выполнено / отменено
}

URGENCY_LABELS: dict[str, str] = {
    "overdue": "Просрочено",
    "due_soon": "Срок 1 день и меньше",
    "due_3days": "Срок через 3 дня",
    "accepted": "Принято",
    "none": "Без срочности",
    "done_ok": "Выполнено",
}

TIER_SORT_ORDER: dict[str, int] = {
    "overdue": 0,
    "due_soon": 1,
    "due_3days": 2,
    "accepted": 3,
    "none": 4,
    "done_ok": 5,
}

_STATUS_LABELS: dict[str, str] = {
    "принято": "принято",
    "вработе": "в работе",
    "отменено": "отменено",
}


class DocflowError(RuntimeError):
    pass


def docflow_base_url() -> str:
    """База OData ERP — список Документ.ТД_Поручения."""
    return odata_base_url()


def docflow_auth() -> tuple[str, str] | None:
    return odata_auth()


def docflow_configured() -> bool:
    return bool(docflow_base_url() and docflow_auth())


def resolve_actor_fio(*, actor_fio: str = "") -> str:
    fio = (actor_fio or "").strip()
    if not fio and regagent_test_login_enabled():
        fio = regagent_test_fio()
    return fio


_ACCEPTED = "принято"


def urgency_tier(
    *,
    due_at: datetime | None,
    done: bool,
    status: str = "",
    completed_at: datetime | None = None,
    today: date | None = None,
) -> tuple[str, str, str]:
    """Цвет по готовности (статус) и срочности (срок). Пастельная палитра."""
    if done:
        return "done_ok", URGENCY_COLORS["done_ok"], URGENCY_LABELS["done_ok"]

    ref = today or date.today()
    status_key = "".join(status.split()).casefold()

    # «Принято» — выполнено с точки зрения готовности; не маркируем как просроченное
    if status_key == _ACCEPTED:
        return "accepted", URGENCY_COLORS["accepted"], URGENCY_LABELS["accepted"]

    if due_at is not None:
        days_left = (due_at.date() - ref).days
        if days_left < 0:
            return "overdue", URGENCY_COLORS["overdue"], URGENCY_LABELS["overdue"]
        if days_left <= 1:
            return "due_soon", URGENCY_COLORS["due_soon"], URGENCY_LABELS["due_soon"]
        if days_left <= 3:
            return "due_3days", URGENCY_COLORS["due_3days"], URGENCY_LABELS["due_3days"]

    return "none", URGENCY_COLORS["none"], URGENCY_LABELS["none"]


def _get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    base = docflow_base_url()
    auth = docflow_auth()
    if not base or not auth:
        raise DocflowError("OData ERP не настроен (ODATA_BASE_URL / учётка)")
    url = f"{base}/{path.lstrip('/')}"
    with httpx.Client(timeout=odata_timeout_sec(), auth=auth) as client:
        response = client.get(url, params=params, headers={"Accept": "application/json"})
    if response.status_code in {401, 402}:
        raise DocflowError(
            "ERP OData отклонил учётку. Проверьте ODATA_USERNAME / ODATA_PASSWORD."
        )
    if response.status_code >= 400:
        text = response.text.lstrip("\ufeff")[:280].replace("\n", " ")
        raise DocflowError(f"ERP OData HTTP {response.status_code}: {text}")
    data = response.json()
    return data if isinstance(data, dict) else {}


def _iter_pages(
    path: str,
    *,
    extra: dict[str, Any] | None = None,
    page_size: int = 100,
    max_rows: int = 400,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    skip = 0
    while skip < max_rows:
        params: dict[str, Any] = {"$top": min(page_size, max_rows - skip)}
        if extra:
            params.update(extra)
        if skip:
            params["$skip"] = skip
        try:
            data = _get(path, params)
        except DocflowError:
            if skip == 0:
                raise
            break
        rows = [row for row in (data.get("value") or []) if isinstance(row, dict)]
        if not rows:
            break
        items.extend(rows)
        if len(rows) < params["$top"]:
            break
        skip += len(rows)
    return items


_USER_CACHE: dict[str, str] | None = None


def load_user_names() -> dict[str, str]:
    global _USER_CACHE
    if _USER_CACHE is not None:
        return _USER_CACHE
    mapping: dict[str, str] = {}
    for row in _iter_pages(
        _USER_ENTITY,
        extra={"$select": "Ref_Key,Description"},
        page_size=200,
        max_rows=4000,
    ):
        key = str(row.get("Ref_Key") or "").strip()
        if key and key != _EMPTY_GUID:
            mapping[key] = " ".join(str(row.get("Description") or "").split())
    _USER_CACHE = mapping
    return mapping


def find_user_key(fio: str, users: dict[str, str] | None = None) -> str:
    needle = " ".join((fio or "").split()).casefold()
    if not needle:
        return ""
    catalog = users if users is not None else load_user_names()
    for key, name in catalog.items():
        if name.casefold() == needle:
            return key
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


def _status_done(status: str) -> bool:
    return " ".join(status.split()).casefold() == _CANCELLED


def _status_label(status: str) -> str:
    key = "".join(status.split()).casefold()
    return _STATUS_LABELS.get(key, status or "не указан")


def _map_line(
    doc: dict[str, Any],
    line: dict[str, Any],
    *,
    performer: str,
    today: date | None = None,
) -> dict[str, Any]:
    status = str(doc.get("Статус") or "").strip()
    status_key = "".join(status.split()).casefold()
    done = _status_done(status)
    created = _parse_odata_dt(doc.get("Date"))
    due = _parse_odata_dt(line.get("СрокИсполнения"))
    title = " ".join(str(line.get("Мероприятие") or "").split())
    subject = " ".join(str(doc.get("ОЧем") or "").split())
    basis = " ".join(str(doc.get("Основание") or "").split())
    tier, color, label = urgency_tier(
        due_at=due,
        done=done,
        status=status,
        completed_at=None,
        today=today,
    )
    ref = str(doc.get("Ref_Key") or line.get("Ref_Key") or "").strip()
    line_no = str(line.get("LineNumber") or "").strip()
    return {
        "id": f"{ref}:{line_no}" if line_no else ref,
        "number": str(doc.get("Number") or "").strip(),
        "line_number": line_no,
        "title": title or subject,
        "subject": subject,
        "status": _status_label(status),
        "done": done,
        "late": (not done)
        and status_key != _ACCEPTED
        and due is not None
        and due.date() < (today or date.today()),
        "created_at": created.isoformat(sep=" ") if created else "",
        "due_at": due.isoformat(sep=" ") if due else "",
        "completed_at": "",
        "comment": basis,
        "approval": _status_label(status),
        "priority": str(line.get("Приоритет") or "").strip(),
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "performer": performer,
        "source": "erp_pm.Document_ТД_Поручения",
        "urgency_tier": tier,
        "color": color,
        "urgency_label": label,
    }


def _doc_number_key(number: str) -> int:
    parts = re.findall(r"\d+", str(number or ""))
    return int(parts[-1]) if parts else 0


def sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сортировка: номер документа по убыванию, затем строка ТЧ."""

    def sort_key(task: dict[str, Any]) -> tuple[int, int]:
        line_raw = str(task.get("line_number") or "0").strip()
        try:
            line_no = int(line_raw)
        except ValueError:
            line_no = 0
        return _doc_number_key(str(task.get("number") or "")), line_no

    return sorted(tasks, key=sort_key, reverse=True)


def list_docflow_tasks(
    *,
    fio: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    only_open: bool = False,
    mine_only: bool = False,
    limit: int = 400,
    today: date | None = None,
) -> tuple[list[dict[str, Any]], str]:
    if not docflow_configured():
        return [], "ERP OData: нет URL/учётки"
    limit = max(1, min(int(limit or 400), 800))
    docs = _iter_pages(
        _DOC_ENTITY,
        extra={"$orderby": "Date desc"},
        page_size=100,
        max_rows=max(limit, 200),
    )
    users = load_user_names()
    actor_key = find_user_key(fio, users) if mine_only and fio else ""
    warning = ""
    if mine_only and fio and not actor_key:
        warning = f"Пользователь «{fio}» не найден в Catalog_Пользователи ERP"

    items: list[dict[str, Any]] = []
    for doc in docs:
        if doc.get("DeletionMark"):
            continue
        created = _parse_odata_dt(doc.get("Date"))
        if date_from is not None and created is not None and created < date_from:
            continue
        if date_to is not None and created is not None and created > date_to:
            continue
        if only_open and _status_done(str(doc.get("Статус") or "")):
            continue
        lines = [row for row in (doc.get("Поручения") or []) if isinstance(row, dict)]
        if not lines:
            lines = [{}]
        for line in lines:
            person_key = str(line.get("ОтветственноеЛицо_Key") or "").strip()
            if mine_only and actor_key and person_key != actor_key:
                continue
            performer = users.get(person_key, "") if person_key and person_key != _EMPTY_GUID else ""
            items.append(_map_line(doc, line, performer=performer, today=today))
            if len(items) >= limit:
                return sort_tasks(items), warning
    return sort_tasks(items), warning


def handle_docflow_tasks(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
) -> dict[str, Any]:
    fio = resolve_actor_fio(actor_fio=actor_fio)
    date_from_raw = str(args.get("date_from") or args.get("dateFrom") or "").strip()
    date_to_raw = str(args.get("date_to") or args.get("dateTo") or "").strip()
    start = parse_date(date_from_raw) if date_from_raw else None
    finish = parse_date(date_to_raw, end=True) if date_to_raw else None

    include_done = args.get("include_done")
    only_open = False if include_done is None else not bool(include_done)
    if "only_open" in args:
        only_open = bool(args.get("only_open"))
    mine_only = bool(args.get("mine_only") or args.get("mineOnly"))

    warning = ""
    try:
        tasks, user_warning = list_docflow_tasks(
            fio=fio,
            date_from=start,
            date_to=finish,
            only_open=only_open,
            mine_only=mine_only,
            limit=int(args.get("limit") or 400),
        )
        if user_warning:
            warning = user_warning
    except DocflowError as exc:
        tasks = []
        warning = str(exc)
    except ErpTaskError as exc:
        tasks = []
        warning = str(exc)

    who = fio or "все"
    return {
        "summary": f"Документ.ТД_Поручения: {len(tasks)} ({who})",
        "fio": fio,
        "count": len(tasks),
        "tasks": tasks,
        "source": "erp_pm.Document_ТД_Поручения",
        "docflow_warning": warning,
    }
