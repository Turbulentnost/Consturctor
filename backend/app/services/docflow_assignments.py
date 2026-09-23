"""Журнал поручений 1С (Document_ТД_Поручения) для вкладки «Документооборот»: страницы и карточка."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

ENTITY = "Document_ТД_Поручения"
FILES_ENTITY = "Catalog_ТД_ПорученияПрисоединенныеФайлы"
_NAVS = ("Руководитель", "Организация", "КтоДоложитОЗавершенииМероприятий", "СекретарьРК")
_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "ОЧем",
    "Основание",
    "Статус",
    "СрокПолногоУстраненияНарушений",
    "ДатаИтоговогоДоклада",
    "ДатаЕженедельногоОтчетаОВыполненииМероприятий",
    "Поручения",
)
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_DEFAULT_PAGE = 40
_MAX_PAGE = 100
_NAME_CHUNK = 25
_STATUSES = {
    "Создано": "Создано",
    "ВРаботе": "В работе",
    "НаПроверке": "На проверке",
    "ВыполненоОжидаетПриемки": "Выполнено, ждёт приёмки",
    "Принято": "Принято",
    "Исполнено": "Исполнено",
    "Закрыто": "Закрыто",
    "Отменено": "Отменено",
}
_CLOSED = {"Принято", "Исполнено", "Закрыто", "Отменено", "ПринятоИЗакрыто"}
_PRIORITY_RANK = {"Критический": 3, "Высокий": 2, "Средний": 1, "Низкий": 0}

_user_names: dict[str, str] = {}


class DocflowAssignmentError(RuntimeError):
    pass


def _q(expression: str) -> str:
    return quote(expression, safe="=,'():")


def _odata(path: str) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        raw = _odata_get({"path": path})
    except OnecToolError as exc:
        raise DocflowAssignmentError(str(exc)) from exc
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = " ".join(str(value).split())
    if not text or text.startswith("0001-01-01") or text == _EMPTY_GUID:
        return ""
    return text


def _nav(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return _text(value.get("Description")) if isinstance(value, dict) else ""


def _status_label(code: str) -> str:
    if code in _STATUSES:
        return _STATUSES[code]
    spaced = re.sub(r"(?<=[а-яё])(?=[А-ЯЁ])", " ", code)
    return spaced[:1].upper() + spaced[1:].lower() if spaced else ""


def _is_open(code: str) -> bool:
    return bool(code) and code not in _CLOSED


def _overdue(due: str, *, open_item: bool) -> bool:
    if not open_item or not due:
        return False
    try:
        return datetime.fromisoformat(due[:19]).date() < datetime.now().date()
    except ValueError:
        return False


def _resolve_users(keys: set[str]) -> None:
    missing = sorted(key for key in keys if _GUID_RE.match(key) and key != _EMPTY_GUID and key not in _user_names)
    for index in range(0, len(missing), _NAME_CHUNK):
        chunk = missing[index : index + _NAME_CHUNK]
        filt = _q(" or ".join(f"Ref_Key eq guid'{key}'" for key in chunk))
        try:
            data = _odata(f"Catalog_Пользователи?$format=json&$top={len(chunk)}&$filter={filt}&$select=Ref_Key,Description")
        except DocflowAssignmentError as exc:
            logger.warning("assignment executors lookup failed: %s", str(exc)[:200])
            return
        for row in data.get("value") or []:
            if isinstance(row, dict):
                _user_names[_text(row.get("Ref_Key"))] = _text(row.get("Description"))
        for key in chunk:
            _user_names.setdefault(key, "")


def _line_view(line: dict[str, Any], *, open_doc: bool) -> dict[str, Any]:
    key = _text(line.get("ОтветственноеЛицо_Key"))
    due = _text(line.get("СрокИсполнения"))
    return {
        "n": int(line.get("LineNumber") or 0),
        "text": _text(line.get("Мероприятие")),
        "due": due,
        "executor": _user_names.get(key, ""),
        "priority": _text(line.get("Приоритет")),
        "overdue": _overdue(due, open_item=open_doc),
    }


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    code = _text(row.get("Статус"))
    open_doc = _is_open(code)
    lines = [
        _line_view(line, open_doc=open_doc)
        for line in (row.get("Поручения") or [])
        if isinstance(line, dict)
    ]
    lines.sort(key=lambda line: line["n"])
    due = _text(row.get("СрокПолногоУстраненияНарушений")) or max((line["due"] for line in lines), default="")
    executors: list[str] = []
    for line in lines:
        if line["executor"] and line["executor"] not in executors:
            executors.append(line["executor"])
    priority = max((line["priority"] for line in lines), key=lambda value: _PRIORITY_RANK.get(value, -1), default="")
    return {
        "id": _text(row.get("Ref_Key")),
        "number": _text(row.get("Number")),
        "date": _text(row.get("Date")),
        "topic": _text(row.get("ОЧем")),
        "basis": _text(row.get("Основание")),
        "status": _status_label(code),
        "status_code": code,
        "open": open_doc,
        "posted": row.get("Posted") is True or str(row.get("Posted")).lower() == "true",
        "head": _nav(row, "Руководитель"),
        "organization": _nav(row, "Организация"),
        "reporter": _nav(row, "КтоДоложитОЗавершенииМероприятий"),
        "secretary": _nav(row, "СекретарьРК"),
        "due": due,
        "final_report": _text(row.get("ДатаИтоговогоДоклада")),
        "weekly_report": _text(row.get("ДатаЕженедельногоОтчетаОВыполненииМероприятий")),
        "overdue": _overdue(due, open_item=open_doc) or any(line["overdue"] for line in lines),
        "priority": priority,
        "executors": executors,
        "lines": lines,
    }


def _query(filters: list[str], *, top: int, skip: int) -> list[dict[str, Any]]:
    select = ",".join([*_FIELDS, *(f"{nav}/Description" for nav in _NAVS)])
    path = (
        f"{ENTITY}?$format=json&$top={top}&$skip={skip}&$orderby=Date desc"
        f"&$filter={_q(' and '.join(filters))}&$select={quote(select, safe=',/')}&$expand={','.join(_NAVS)}"
    )
    rows = [row for row in (_odata(path).get("value") or []) if isinstance(row, dict)]
    _resolve_users(
        {
            _text(line.get("ОтветственноеЛицо_Key"))
            for row in rows
            for line in (row.get("Поручения") or [])
            if isinstance(line, dict)
        }
    )
    return rows


def _day(raw: Any, *, end: bool) -> str:
    text = str(raw or "").strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    return f"{text}T23:59:59" if end else f"{text}T00:00:00"


def list_assignments(args: dict[str, Any]) -> dict[str, Any]:
    top = max(1, min(int(args.get("top") or _DEFAULT_PAGE), _MAX_PAGE))
    skip = max(0, int(args.get("skip") or 0))
    filters = ["DeletionMark eq false"]
    start = _day(args.get("date_from"), end=False)
    finish = _day(args.get("date_to"), end=True)
    if start:
        filters.append(f"Date ge datetime'{start}'")
    if finish:
        filters.append(f"Date le datetime'{finish}'")
    status = re.sub(r"[^A-Za-zА-Яа-яЁё]", "", str(args.get("status") or ""))
    if status:
        filters.append(f"Статус eq '{status}'")
    raw = _query(filters, top=top, skip=skip)
    rows = [_row_view(row) for row in raw]
    return {
        "summary": f"Поручения: {len(rows)}",
        "rows": rows,
        "count": len(rows),
        "skip": skip,
        "next_skip": skip + len(raw),
        "has_more": len(raw) >= top,
        "statuses": [{"code": code, "label": label} for code, label in _STATUSES.items()],
    }


def _tasks(ref: str) -> list[dict[str, Any]]:
    subject = _q(f"Предмет eq cast(guid'{ref}', '{ENTITY}')")
    path = (
        f"Task_ЗадачаИсполнителя?$format=json&$top=50&$filter={subject}"
        "&$select=Ref_Key,Date,Description,Executed,СрокИсполнения,ДатаИсполнения,РезультатВыполнения,Исполнитель"
    )
    try:
        rows = [row for row in (_odata(path).get("value") or []) if isinstance(row, dict)]
    except DocflowAssignmentError as exc:
        logger.warning("assignment %s tasks failed: %s", ref, exc)
        return []
    _resolve_users({_text(row.get("Исполнитель")) for row in rows})
    out = [
        {
            "id": _text(row.get("Ref_Key")),
            "performer": _user_names.get(_text(row.get("Исполнитель")), ""),
            "title": _text(row.get("Description")),
            "result": _text(row.get("РезультатВыполнения")),
            "begin": _text(row.get("Date")),
            "due": _text(row.get("СрокИсполнения")),
            "done_at": _text(row.get("ДатаИсполнения")),
            "executed": row.get("Executed") is True or str(row.get("Executed")).lower() == "true",
        }
        for row in rows
    ]
    out.sort(key=lambda task: task["begin"])
    return out


def _files(ref: str) -> list[dict[str, str]]:
    filt = _q(f"ВладелецФайла_Key eq guid'{ref}'")
    try:
        data = _odata(
            f"{FILES_ENTITY}?$format=json&$top=50&$filter={filt}&$select=Ref_Key,Description,Расширение,Размер,ДатаСоздания"
        )
    except DocflowAssignmentError as exc:
        logger.warning("assignment %s files failed: %s", ref, exc)
        return []
    return [
        {
            "id": _text(row.get("Ref_Key")),
            "name": _text(row.get("Description")),
            "extension": _text(row.get("Расширение")),
            "size": _text(row.get("Размер")),
            "created": _text(row.get("ДатаСоздания")),
        }
        for row in data.get("value") or []
        if isinstance(row, dict)
    ]


def assignment_card(args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("ref_key") or args.get("id") or "").strip()
    if not _GUID_RE.match(ref):
        raise DocflowAssignmentError("Нужен Ref_Key поручения")
    # $expand работает только в списке: одиночный GET по guid его не принимает.
    raw = _query([f"Ref_Key eq guid'{ref}'"], top=1, skip=0)
    if not raw:
        raise DocflowAssignmentError("1С не вернула поручение")
    view = _row_view(raw[0])
    tasks = _tasks(ref)
    lines_total = len(view["lines"])
    return {
        "summary": f"Поручение {view['number']}",
        "assignment": view,
        "tasks": tasks,
        "files": _files(ref),
        "progress": {
            "lines": lines_total,
            "overdue_lines": sum(1 for line in view["lines"] if line["overdue"]),
            "tasks": len(tasks),
            "tasks_done": sum(1 for task in tasks if task["executed"]),
        },
    }


def handle_docflow_assignments(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return list_assignments(args)
    except DocflowAssignmentError as exc:
        raise OnecToolError(str(exc)) from exc


def handle_docflow_assignment_card(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return assignment_card(args)
    except DocflowAssignmentError as exc:
        raise OnecToolError(str(exc)) from exc
