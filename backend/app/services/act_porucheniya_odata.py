"""Реестр поручений ACT/АСТ (Document_ТД_Поручения) через OData 1С ERP.

Колонки соответствуют журналу «Поручения (ТД)» в 1С:
Дата, Номер, О чём, Основание, дата еженедельного отчёта, срок устранения,
кто доложит, секретарь РК.

Фильтрация только по префиксу номера ACT/АСТ и DeletionMark.
Статус документа (ВРаботе / Принято / Создано и т.д.) в запрос не входит.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

ProgressCallback = Callable[[str], None]
from urllib.parse import quote

import httpx

from app.config import settings

ENTITY = "Document_ТД_Поручения"
MODULE_ID = "act_porucheniya_registry"
MODULE_TITLE = "Реестр поручений ACT (ТД)"

_ACT_PREFIXES = ("АСТ", "ACT", "АСТ", "аст", "act")
_REF_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def odata_ready() -> bool:
    return bool(
        settings.odata_base_url.strip()
        and (
            (settings.erp_login.strip() and settings.erp_password.strip())
            or (settings.odata_username.strip() and settings.odata_password.strip())
        )
    )


def _auth() -> tuple[str, str]:
    if settings.erp_login and settings.erp_password:
        return settings.erp_login, settings.erp_password
    return settings.odata_username, settings.odata_password


def _odata_url(path: str) -> str:
    base = settings.odata_base_url.rstrip("/")
    cleaned = path.lstrip("/")
    safe = "/()'=,:$"
    if "?" in cleaned:
        head, query = cleaned.split("?", 1)
        return f"{base}/{quote(head, safe=safe)}?{query}"
    return f"{base}/{quote(cleaned, safe=safe)}"


def normalize_act_number(number: str) -> str:
    """АСТ00-00088 → ACT00-00088 для отображения в Excel."""
    text = (number or "").strip()
    if not text:
        return ""
    if text.upper().startswith("АСТ"):
        return "ACT" + text[3:]
    return text


def is_act_number(number: str) -> bool:
    text = (number or "").strip().upper()
    return text.startswith("ACT") or text.startswith("АСТ")


def _format_dt(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text or text.startswith("0001-01-01"):
        return ""
    text = text.replace("T", " ")[:19]
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(text[:19])
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except ValueError:
        return text


def _ref_description(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("Description", "Наименование", "Presentation"):
            text = str(value.get(key) or "").strip()
            if text:
                return text
        ref = str(value.get("Ref_Key") or "")
        if _REF_KEY_RE.match(ref):
            return ""
    if value in (None, ""):
        return ""
    text = str(value).strip()
    if _REF_KEY_RE.match(text):
        return ""
    return text


def _normalize_basis(value: Any) -> str:
    if isinstance(value, dict):
        return _ref_description(value)
    text = str(value or "").strip()
    if not text or _REF_KEY_RE.match(text):
        return ""
    return text


def _format_date_only(raw: Any) -> str:
    text = _format_dt(raw)
    if not text:
        return ""
    return text.split(" ")[0]


def _normalize_task_line(line: dict[str, Any]) -> dict[str, Any]:
    task = str(line.get("Мероприятие") or "").strip()
    raw_ln = line.get("LineNumber")
    try:
        line_number = int(raw_ln) if raw_ln not in (None, "") else 0
    except (TypeError, ValueError):
        line_number = 0
    return {
        "line_number": line_number,
        "task": task,
        "executor_key": str(line.get("ОтветственноеЛицо_Key") or "").strip(),
        "executor": "",
        "deadline": _format_date_only(line.get("СрокИсполнения")),
        "deadline_raw": str(line.get("СрокИсполнения") or "")[:19],
        "priority": str(line.get("Приоритет") or "").strip(),
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    number = str(row.get("Number") or "")
    raw_lines = row.get("Поручения") or []
    task_lines: list[dict[str, Any]] = []
    activities: list[str] = []
    if isinstance(raw_lines, list):
        for line in raw_lines:
            if not isinstance(line, dict):
                continue
            normalized = _normalize_task_line(line)
            if normalized["task"]:
                activities.append(normalized["task"])
                task_lines.append(normalized)
    return {
        "ref_key": str(row.get("Ref_Key") or ""),
        "number": number,
        "number_display": normalize_act_number(number),
        "date": _format_dt(row.get("Date")),
        "about": str(row.get("ОЧем") or "").strip(),
        "basis": _normalize_basis(row.get("Основание")),
        "weekly_report_date": _format_dt(row.get("ДатаЕженедельногоОтчетаОВыполненииМероприятий")),
        "final_deadline": _format_dt(row.get("СрокПолногоУстраненияНарушений")),
        "final_deadline_raw": str(row.get("СрокПолногоУстраненияНарушений") or "")[:19],
        "reporter": _ref_description(row.get("КтоДоложитОЗавершенииМероприятий")),
        "secretary": _ref_description(row.get("СекретарьРК")),
        "status": str(row.get("Статус") or "").strip(),
        "activities": activities,
        "activity_summary": "; ".join(activities[:3]),
        "task_lines": task_lines,
        "task_line_count": len(task_lines),
        "posted": bool(row.get("Posted")),
        "deletion_mark": bool(row.get("DeletionMark")),
    }


_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"


def _resolve_executor_name(client: httpx.Client, base: str, key: str, cache: dict[str, str]) -> str:
    if not key or key == _EMPTY_GUID:
        return ""
    if key in cache:
        return cache[key]
    name = ""
    try:
        response = client.get(f"{base}/Catalog_Пользователи(guid'{key}')?$format=json")
        if response.status_code == 200:
            payload = response.json()
            name = str(payload.get("Description") or "").strip()
            fl_key = str(payload.get("ФизическоеЛицо_Key") or "")
            if fl_key and fl_key != _EMPTY_GUID:
                fl_resp = client.get(f"{base}/Catalog_ФизическиеЛица(guid'{fl_key}')?$format=json")
                if fl_resp.status_code == 200:
                    name = str(fl_resp.json().get("Description") or name).strip()
    except Exception:  # noqa: BLE001
        name = ""
    cache[key] = name
    return name


def _emit_progress(on_progress: ProgressCallback | None, message: str) -> None:
    if on_progress:
        on_progress(message)


def resolve_task_line_executors(
    documents: list[dict[str, Any]],
    *,
    on_progress: ProgressCallback | None = None,
) -> None:
    """Подставить ФИО исполнителей в task_lines (in-place)."""
    if not documents or not odata_ready():
        return
    base = settings.odata_base_url.rstrip("/")
    keys: set[str] = set()
    for doc in documents:
        for line in doc.get("task_lines") or []:
            key = str(line.get("executor_key") or "")
            if key and key != _EMPTY_GUID:
                keys.add(key)
    if not keys:
        return
    key_list = sorted(keys)
    _emit_progress(
        on_progress,
        f"OData: подставляю ФИО исполнителей ({len(key_list)} уникальных)…",
    )
    cache: dict[str, str] = {}
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=_auth()) as client:
        for index, key in enumerate(key_list, start=1):
            _resolve_executor_name(client, base, key, cache)
            if index == 1 or index == len(key_list) or index % 10 == 0:
                _emit_progress(
                    on_progress,
                    f"OData: исполнители {index}/{len(key_list)}…",
                )
    for doc in documents:
        for line in doc.get("task_lines") or []:
            key = str(line.get("executor_key") or "")
            line["executor"] = cache.get(key, "")


def _build_query(*, limit: int, skip: int = 0, reporter_fio: str = "") -> str:
    limit = max(1, min(int(limit or 100), 200))
    skip = max(0, int(skip or 0))
    # Только номер ACT/АСТ и не помечен на удаление — без фильтра по Статус/Posted.
    filters = ["DeletionMark eq false", "startswith(Number,'АСТ')"]
    reporter = (reporter_fio or "").strip().replace("'", "''")
    if reporter:
        filters.append(
            f"substringof('{reporter}', КтоДоложитОЗавершенииМероприятий/Description)"
        )
    filter_expr = " and ".join(filters)
    return (
        f"{ENTITY}?$format=json"
        f"&$top={limit}"
        f"&$skip={skip}"
        f"&$orderby=Date desc"
        f"&$filter={filter_expr}"
        f"&$expand=КтоДоложитОЗавершенииМероприятий,СекретарьРК"
    )


def _fetch_page(
    *,
    limit: int,
    skip: int,
    reporter_fio: str = "",
    client: httpx.Client | None = None,
) -> tuple[list[dict[str, Any]], str]:
    path = _build_query(limit=limit, skip=skip, reporter_fio=reporter_fio)
    url = _odata_url(path)
    if client is None:
        with httpx.Client(timeout=settings.odata_timeout_sec, auth=_auth()) as owned:
            return _fetch_page(
                limit=limit,
                skip=skip,
                reporter_fio=reporter_fio,
                client=owned,
            )
    response = client.get(url, headers={"Accept": "application/json"})
    if response.status_code >= 400:
        raise RuntimeError(f"OData HTTP {response.status_code}: {response.text[:300]}")
    payload = response.json()
    rows = list(payload.get("value") or [])
    documents = [_normalize_row(row) for row in rows if isinstance(row, dict)]
    documents = [doc for doc in documents if is_act_number(doc.get("number", ""))]
    return documents, path


def fetch_act_porucheniya_registry(
    *,
    limit: int = 0,
    reporter_fio: str = "",
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Загрузить реестр поручений ACT/АСТ из OData (все статусы)."""
    if not odata_ready():
        return {
            "summary": "OData не настроен (ODATA_BASE_URL / ERP_LOGIN)",
            "count": 0,
            "documents": [],
            "source": "odata-unconfigured",
            "module": MODULE_ID,
            "module_title": MODULE_TITLE,
        }

    page_size = 100
    max_total = max(1, int(limit)) if limit else 1000
    documents: list[dict[str, Any]] = []
    last_path = ""
    skip = 0
    page_num = 0
    try:
        with httpx.Client(timeout=settings.odata_timeout_sec, auth=_auth()) as client:
            while len(documents) < max_total:
                batch = min(page_size, max_total - len(documents))
                page_num += 1
                _emit_progress(
                    on_progress,
                    f"OData: запрос страницы {page_num} (skip={skip}, top={batch})…",
                )
                page_docs, last_path = _fetch_page(
                    limit=batch,
                    skip=skip,
                    reporter_fio=reporter_fio,
                    client=client,
                )
                if not page_docs:
                    break
                documents.extend(page_docs)
                _emit_progress(
                    on_progress,
                    f"OData: получено {len(documents)} документов ACT/АСТ…",
                )
                if len(page_docs) < batch:
                    break
                skip += len(page_docs)
    except Exception as exc:  # noqa: BLE001
        if not documents:
            err_text = str(exc).strip() or type(exc).__name__
            hint = ""
            if "timed out" in err_text.casefold() or "timeout" in err_text.casefold():
                hint = (
                    " Превышено время ответа 1С (полная выгрузка ~1–2 мин). "
                    "Проверьте VPN/сеть и повторите запрос."
                )
            return {
                "summary": f"OData error: {err_text}.{hint}".strip(),
                "count": 0,
                "documents": [],
                "source": "odata-error",
                "odata_error": err_text,
                "module": MODULE_ID,
                "module_title": MODULE_TITLE,
            }

    try:
        resolve_task_line_executors(documents, on_progress=on_progress)
    except Exception as exc:  # noqa: BLE001
        _emit_progress(
            on_progress,
            f"OData: ФИО исполнителей не загружены ({exc}) — Excel без ФИО.",
        )
    task_count = sum(int(doc.get("task_line_count") or 0) for doc in documents)

    return {
        "summary": (
            f"Реестр поручений ACT (ТД): {len(documents)} документов, "
            f"{task_count} задач в табличной части «Поручения»"
        ),
        "count": len(documents),
        "task_count": task_count,
        "documents": documents,
        "entity": ENTITY,
        "source": "odata-act-registry",
        "module": MODULE_ID,
        "module_title": MODULE_TITLE,
        "odata_path": last_path,
        "status_filter": None,
    }
