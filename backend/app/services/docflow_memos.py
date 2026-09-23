"""Служебные записки 1С: журнал (ERP OData) + маршрут согласования (задачи 1С:Документооборот)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

MEMO_ENTITY = "Document_ТД_СлужебнаяЗаписка"
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_SECRET_RE = re.compile(r"конфиденц|секрет|тайн|дсп|служебного пользования", re.IGNORECASE)
_LIST_NAVS = ("Ответственный", "Подразделение", "ГрифДоступа")
_CARD_NAVS = ("Ответственный", "Подразделение", "Организация", "ГрифДоступа", "Приоритет", "Проект", "ИсполнительУД")
_LIST_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "ТемаСлужебнойЗаписки",
    "ТемаСовещания",
    "СрокИсполнения",
    "Направление",
)
_DEFAULT_PAGE = 40
_MAX_PAGE = 100
_DIRECTIONS = {
    "ПрочиеВнутренние": "Прочие внутренние",
    "УправлениеДелами": "Управление делами",
    "ОперационныйДиректор": "Операционный директор",
    "ФинансовыйДиректор": "Финансовый директор",
    "КоммерческийДиректор": "Коммерческий директор",
    "РевизионнаяКомиссия": "Ревизионная комиссия",
}
_STATUSES = {"НеСогласована": "Не согласована", "Согласована": "Согласована"}
_CARD_LABELS = {
    "Number": "Номер",
    "Date": "Дата",
    "Posted": "Проведена",
    "Статус": "Статус",
    "ТемаСлужебнойЗаписки": "Тема",
    "ТемаСовещания": "Тема совещания",
    "Направление": "Направление",
    "Ответственный": "От кого",
    "Подразделение": "Подразделение",
    "Организация": "Организация",
    "ГрифДоступа": "Гриф доступа",
    "Приоритет": "Приоритет",
    "Проект": "Проект",
    "ИсполнительУД": "Исполнитель УД",
    "СрокИсполнения": "Срок исполнения",
    "ДатаИсполненияУД": "Дата исполнения УД",
    "БизнесПроцессСтартован": "Согласование запущено",
    "УтвержденоНачальникомУД": "Утверждено начальником УД",
    "КоличествоПереносов": "Переносов срока",
    "ИсторияПереносов": "История переносов",
    "Комментарий": "Комментарий",
    "ДатаПроведенияСовещания": "Дата совещания",
    "МестоПроведенияСовещания": "Место совещания",
    "ТекстСлужебнойЗаписки": "Текст",
}


class DocflowMemoError(RuntimeError):
    pass


def _q(expression: str) -> str:
    return quote(expression, safe="=,'():")


def _odata(path: str) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        raw = _odata_get({"path": path})
    except OnecToolError as exc:
        raise DocflowMemoError(str(exc)) from exc
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = str(value).strip()
    if not text or text.startswith("0001-01-01") or text == _EMPTY_GUID:
        return ""
    return text


def _nav_name(row: dict[str, Any], nav: str) -> str:
    value = row.get(nav)
    if isinstance(value, dict):
        return _text(value.get("Description") or value.get("Наименование"))
    return ""


_subject_names: dict[str, str] = {}


def _subject(row: dict[str, Any]) -> str:
    """Тема бывает строкой или ссылкой на Catalog_ТД_ТемыСлужебныхЗаписок."""
    raw = str(row.get("ТемаСлужебнойЗаписки") or "").strip()
    if raw and _GUID_RE.match(raw) and raw != _EMPTY_GUID:
        if raw not in _subject_names:
            try:
                data = _odata(f"Catalog_ТД_ТемыСлужебныхЗаписок(guid'{raw}')?$format=json&$select=Description")
                _subject_names[raw] = _text(data.get("Description"))
            except DocflowMemoError:
                _subject_names[raw] = ""
        return _subject_names[raw] or _text(row.get("ТемаСовещания"))
    return _text(raw) or _text(row.get("ТемаСовещания"))


def _bool(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _strip_html(value: str) -> str:
    text = re.sub(r"<style[\s\S]*?</style>", " ", value, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    for entity, char in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"')):
        text = text.replace(entity, char)
    return re.sub(r"\s+", " ", text).strip()


def is_secret(row: dict[str, Any]) -> bool:
    return bool(_SECRET_RE.search(_nav_name(row, "ГрифДоступа")))


def _day_bound(raw: Any, *, end: bool) -> str:
    text = str(raw or "").strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    return f"{text}T23:59:59" if end else f"{text}T00:00:00"


def _task_view(row: dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "id": _text(row.get("id")),
        "performer": _text(row.get("performer")),
        "author": _text(row.get("author")),
        "step": _text(row.get("step")) or _text(row.get("name")).split('"')[0].strip(),
        "name": _text(row.get("name")),
        "description": _text(row.get("description")),
        "begin": _text(row.get("begin")),
        "due": _text(row.get("due")),
        "executed": bool(row.get("executed")),
        "execution_mark": _text(row.get("execution_mark")),
        "source": source,
    }


def _route_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    performers: list[str] = []
    for task in tasks:
        name = task.get("performer") or ""
        if name and name not in performers:
            performers.append(name)
    dues = sorted(task["due"] for task in tasks if task.get("due") and not task.get("executed"))
    return {
        "assignees": performers,
        "due": dues[0] if dues else "",
        "open_tasks": sum(1 for task in tasks if not task.get("executed")),
    }


def _list_row(row: dict[str, Any]) -> dict[str, Any]:
    from app.tools.onec.dok_soap import memo_open_tasks

    number = _text(row.get("Number"))
    tasks = [_task_view(task, source="docflow") for task in memo_open_tasks(number)]
    route = _route_summary(tasks)
    status = _text(row.get("Статус"))
    return {
        "id": _text(row.get("Ref_Key")),
        "number": number,
        "date": _text(row.get("Date")),
        "subject": _subject(row),
        "status": _STATUSES.get(status, status),
        "approved": status == "Согласована",
        "posted": _bool(row.get("Posted")),
        "from_whom": _nav_name(row, "Ответственный"),
        "department": _nav_name(row, "Подразделение"),
        "direction": _DIRECTIONS.get(_text(row.get("Направление")), _text(row.get("Направление"))),
        "assignees": route["assignees"],
        "due": _text(row.get("СрокИсполнения")) or route["due"],
        "open_tasks": route["open_tasks"],
    }


def list_memos(args: dict[str, Any]) -> dict[str, Any]:
    top = max(1, min(int(args.get("top") or _DEFAULT_PAGE), _MAX_PAGE))
    skip = max(0, int(args.get("skip") or 0))
    filters = ["DeletionMark eq false"]
    start = _day_bound(args.get("date_from"), end=False)
    finish = _day_bound(args.get("date_to"), end=True)
    if start:
        filters.append(f"Date ge datetime'{start}'")
    if finish:
        filters.append(f"Date le datetime'{finish}'")
    select = ",".join([*_LIST_FIELDS, *(f"{nav}/Description" for nav in _LIST_NAVS)])
    odata_filter = _q(" and ".join(filters))
    path = (
        f"{MEMO_ENTITY}?$format=json&$top={top}&$skip={skip}&$orderby=Date desc"
        f"&$filter={odata_filter}&$select={quote(select, safe=',/')}&$expand={','.join(_LIST_NAVS)}"
    )
    data = _odata(path)
    raw = [row for row in (data.get("value") or []) if isinstance(row, dict)]
    rows = [_list_row(row) for row in raw if not is_secret(row)]
    return {
        "summary": f"Служебные записки: {len(rows)} (скрыто конфиденциальных: {len(raw) - len(rows)})",
        "rows": rows,
        "count": len(rows),
        "skip": skip,
        "next_skip": skip + len(raw),
        "has_more": len(raw) >= top,
        "hidden_secret": len(raw) - len(rows),
    }


def _card_fields(row: dict[str, Any]) -> list[dict[str, str]]:
    fields: list[dict[str, str]] = []
    for key, label in _CARD_LABELS.items():
        if key in _CARD_NAVS:
            value = _nav_name(row, key)
        else:
            raw = row.get(key)
            if isinstance(raw, bool) or str(raw).strip().lower() in {"true", "false"}:
                value = "Да" if _bool(raw) else ""
            else:
                value = _text(raw)
        if key == "ТекстСлужебнойЗаписки":
            value = _strip_html(value)
        if key == "ТемаСлужебнойЗаписки":
            value = _subject(row)
        if key == "Статус":
            value = _STATUSES.get(value, value)
        if key == "Направление":
            value = _DIRECTIONS.get(value, value)
        if key in {"КоличествоПереносов"} and value in {"0", ""}:
            value = ""
        if value:
            fields.append({"key": key, "label": label, "value": value})
    return fields


def _erp_tasks(ref: str) -> list[dict[str, Any]]:
    subject_filter = _q(f"Предмет eq cast(guid'{ref}', '{MEMO_ENTITY}')")
    path = (
        f"Task_ЗадачаИсполнителя?$format=json&$top=50&$filter={subject_filter}"
        "&$select=Ref_Key,Date,Description,Executed,СрокИсполнения,ДатаИсполнения,РезультатВыполнения,Исполнитель,Автор"
    )
    try:
        rows = [row for row in (_odata(path).get("value") or []) if isinstance(row, dict)]
    except DocflowMemoError as exc:
        logger.warning("memo %s ERP tasks failed: %s", ref, exc)
        return []
    names = _user_names({_text(row.get("Исполнитель")) for row in rows} | {_text(row.get("Автор")) for row in rows})
    return [
        {
            "id": _text(row.get("Ref_Key")),
            "performer": names.get(_text(row.get("Исполнитель")), ""),
            "author": names.get(_text(row.get("Автор")), ""),
            "step": "Задача ERP",
            "name": _text(row.get("Description")),
            "description": _text(row.get("РезультатВыполнения")),
            "begin": _text(row.get("Date")),
            "due": _text(row.get("СрокИсполнения")),
            "done_at": _text(row.get("ДатаИсполнения")),
            "executed": _bool(row.get("Executed")),
            "execution_mark": "",
            "source": "erp",
        }
        for row in rows
    ]


def _user_names(keys: set[str]) -> dict[str, str]:
    names: dict[str, str] = {}
    for key in sorted(key for key in keys if _GUID_RE.match(key or "")):
        try:
            data = _odata(f"Catalog_Пользователи(guid'{key}')?$format=json&$select=Description")
        except DocflowMemoError:
            continue
        name = _text(data.get("Description"))
        if name:
            names[key] = name
    return names


def _docflow_history(open_rows: list[dict[str, Any]], args: dict[str, Any]) -> list[dict[str, Any]]:
    """Все задачи документа ДО под сессией пользователя; без пароля — только открытые из выгрузки."""
    target = next((row for row in open_rows if row.get("target_id")), None)
    user = str(args.get("fio") or args.get("erp_login") or "").strip()
    password = str(args.get("password") or args.get("erp_password") or "").strip()
    if not target or not user or not password:
        return []
    from app.tools.onec.dok_soap import load_config, tasks_for_target

    try:
        config = load_config(username=user, password=password, require_user=True)
        return tasks_for_target(
            config,
            str(target.get("target_id") or ""),
            str(target.get("target_type") or ""),
            timeout=25.0,
        )
    except (RuntimeError, ValueError) as exc:
        logger.warning("memo docflow history %s failed: %s", target.get("target_id"), str(exc)[:200])
        return []


def memo_card(args: dict[str, Any]) -> dict[str, Any]:
    from app.tools.onec.dok_soap import memo_open_tasks

    ref = str(args.get("ref_key") or args.get("id") or "").strip()
    if not _GUID_RE.match(ref):
        raise DocflowMemoError("Нужен Ref_Key служебной записки")
    # $expand работает только в списке: одиночный GET по guid его не принимает.
    ref_filter = _q(f"Ref_Key eq guid'{ref}'")
    found = _odata(
        f"{MEMO_ENTITY}?$format=json&$top=1&$filter={ref_filter}&$expand={','.join(_CARD_NAVS)}"
    ).get("value") or []
    row = found[0] if found and isinstance(found[0], dict) else {}
    if not row:
        raise DocflowMemoError("1С не вернула служебную записку")
    if is_secret(row):
        raise DocflowMemoError("Служебная записка с ограниченным грифом доступа — в Оркестраторе не показывается.")
    number = _text(row.get("Number"))
    open_rows = memo_open_tasks(number)
    history = _docflow_history(open_rows, args) or open_rows
    tasks = [_task_view(task, source="docflow") for task in history] + _erp_tasks(ref)
    tasks.sort(key=lambda task: task.get("begin") or "")
    status = _text(row.get("Статус"))
    executed = sum(1 for task in tasks if task.get("executed"))
    return {
        "summary": f"Служебная записка {number}",
        "memo": {
            "id": ref,
            "number": number,
            "date": _text(row.get("Date")),
            "subject": _subject(row),
            "status": _STATUSES.get(status, status),
            "approved": status == "Согласована",
            "posted": _bool(row.get("Posted")),
            "from_whom": _nav_name(row, "Ответственный"),
            "text": _strip_html(_text(row.get("ТекстСлужебнойЗаписки"))),
            "fields": _card_fields(row),
        },
        "tasks": tasks,
        "route": {
            **_route_summary(tasks),
            "total": len(tasks),
            "executed": executed,
            "history_complete": bool(history is not open_rows),
        },
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def handle_docflow_memos(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    try:
        return list_memos(args)
    except DocflowMemoError as exc:
        from app.services.onec_tools import OnecToolError

        raise OnecToolError(str(exc)) from exc


def handle_docflow_memo_card(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    try:
        return memo_card(args)
    except DocflowMemoError as exc:
        from app.services.onec_tools import OnecToolError

        raise OnecToolError(str(exc)) from exc
