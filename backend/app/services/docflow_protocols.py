"""Журнал протоколов совещаний 1С (Document_ТД_Протокол) для вкладки «Документооборот»."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

ENTITY = "Document_ТД_Протокол"
_NAVS = (
    "Подготовил",
    "ГрифДоступа",
    "Ответственный",
    "Руководитель",
    "ТемаСовещания",
    "Проект",
    "Подразделение",
    "Кабинет",
)
_FIELDS = (
    "Ref_Key",
    "Number",
    "Date",
    "Posted",
    "Статус",
    "ВидСовещания",
    "ДатаСледующегоСовещания",
    "ЗадачиРазосланы",
    "ВремяНачалаСовещания",
    "ВремяОкончанияСовещания",
    "КраткийСоставДокумента",
    "Комментарий",
)
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_SECRET_RE = re.compile(r"конфиденц|секрет|тайн|дсп|служебного пользования", re.IGNORECASE)
_DEFAULT_PAGE = 40
_MAX_PAGE = 100
_NAME_CHUNK = 25
_PEOPLE_CATALOGS = ("Catalog_Пользователи", "Catalog_ФизическиеЛица")
STATUSES = {"Подготовлен": "Подготовлен", "НаИсполнении": "На исполнении", "Закрыт": "Закрыт"}
KINDS = {"Отчетное": "Отчётное", "Внеплановое": "Внеплановое", "Селекторное": "Селекторное"}

_names: dict[str, str] = {}


class DocflowProtocolError(RuntimeError):
    pass


def _q(expression: str) -> str:
    return quote(expression, safe="=,'():")


def _odata(path: str) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError, _odata_get

    try:
        raw = _odata_get({"path": path})
    except OnecToolError as exc:
        raise DocflowProtocolError(str(exc)) from exc
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list)):
        return ""
    text = " ".join(str(value).split())
    if not text or text.startswith("0001-01-01T00:00:00") or text == _EMPTY_GUID:
        return ""
    return text


def _nav(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return _text(value.get("Description")) if isinstance(value, dict) else ""


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() == "true"


def _time(value: Any) -> str:
    """Время совещания хранится как 0001-01-01T15:00:00."""
    text = str(value or "")
    match = re.search(r"T(\d{2}:\d{2})", text)
    return match.group(1) if match and match.group(1) != "00:00" else ""


def _label(value: str, table: dict[str, str]) -> str:
    if value in table:
        return table[value]
    spaced = re.sub(r"(?<=[а-яё])(?=[А-ЯЁ])", " ", value)
    return spaced[:1].upper() + spaced[1:].lower() if spaced else ""


def is_secret(row: dict[str, Any]) -> bool:
    return bool(_SECRET_RE.search(_nav(row, "ГрифДоступа")))


def _resolve_names(keys: set[str]) -> None:
    """Ответственные — пользователи, участники — физические лица: ищем в обоих справочниках."""
    missing = sorted(key for key in keys if _GUID_RE.match(key) and key != _EMPTY_GUID and key not in _names)
    for catalog in _PEOPLE_CATALOGS:
        if not missing:
            return
        found: set[str] = set()
        for index in range(0, len(missing), _NAME_CHUNK):
            chunk = missing[index : index + _NAME_CHUNK]
            filt = _q(" or ".join(f"Ref_Key eq guid'{key}'" for key in chunk))
            try:
                data = _odata(f"{catalog}?$format=json&$top={len(chunk)}&$filter={filt}&$select=Ref_Key,Description")
            except DocflowProtocolError as exc:
                logger.warning("protocol names lookup in %s failed: %s", catalog, str(exc)[:200])
                break
            for row in data.get("value") or []:
                if isinstance(row, dict) and _text(row.get("Description")):
                    _names[_text(row.get("Ref_Key"))] = _text(row.get("Description"))
                    found.add(_text(row.get("Ref_Key")))
        missing = [key for key in missing if key not in found]
    for key in missing:
        _names.setdefault(key, "")


def _participants(row: dict[str, Any]) -> list[str]:
    raw = _text(row.get("КраткийСоставДокумента"))
    return [part.strip() for part in raw.split(";") if part.strip()]


def _row_view(row: dict[str, Any]) -> dict[str, Any]:
    status = _text(row.get("Статус"))
    kind = _text(row.get("ВидСовещания"))
    start, finish = _time(row.get("ВремяНачалаСовещания")), _time(row.get("ВремяОкончанияСовещания"))
    return {
        "id": _text(row.get("Ref_Key")),
        "number": _text(row.get("Number")),
        "date": _text(row.get("Date")),
        "time": f"{start}–{finish}" if start and finish else start,
        "status": _label(status, STATUSES),
        "status_code": status,
        "closed": status == "Закрыт",
        "kind": _label(kind, KINDS),
        "kind_code": kind,
        "topic": _nav(row, "ТемаСовещания"),
        "head": _nav(row, "Руководитель"),
        "prepared_by": _nav(row, "Подготовил"),
        "responsible": _nav(row, "Ответственный"),
        "department": _nav(row, "Подразделение"),
        "room": _nav(row, "Кабинет"),
        "project": _nav(row, "Проект"),
        "access": _nav(row, "ГрифДоступа"),
        "next_meeting": _text(row.get("ДатаСледующегоСовещания")),
        "tasks_sent": _flag(row.get("ЗадачиРазосланы")),
        "posted": _flag(row.get("Posted")),
        "comment": _text(row.get("Комментарий")),
        "participants": _participants(row),
    }


def _day(raw: Any, *, end: bool) -> str:
    text = str(raw or "").strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return ""
    return f"{text}T23:59:59" if end else f"{text}T00:00:00"


def _clean_code(value: Any) -> str:
    return re.sub(r"[^A-Za-zА-Яа-яЁё]", "", str(value or ""))


def _list_path(filters: list[str], *, top: int, skip: int, with_parts: bool) -> str:
    select = f"&$select={quote(','.join([*_FIELDS, *(f'{nav}/Description' for nav in _NAVS)]), safe=',/')}"
    return (
        f"{ENTITY}?$format=json&$top={top}&$skip={skip}&$orderby=Date desc"
        f"&$filter={_q(' and '.join(filters))}{'' if with_parts else select}&$expand={','.join(_NAVS)}"
    )


def list_protocols(args: dict[str, Any]) -> dict[str, Any]:
    top = max(1, min(int(args.get("top") or _DEFAULT_PAGE), _MAX_PAGE))
    skip = max(0, int(args.get("skip") or 0))
    filters = ["DeletionMark eq false"]
    start = _day(args.get("date_from"), end=False)
    finish = _day(args.get("date_to"), end=True)
    if start:
        filters.append(f"Date ge datetime'{start}'")
    if finish:
        filters.append(f"Date le datetime'{finish}'")
    status = _clean_code(args.get("status"))
    if status:
        filters.append(f"Статус eq '{status}'")
    kind = _clean_code(args.get("kind"))
    if kind:
        filters.append(f"ВидСовещания eq '{kind}'")
    raw = [row for row in (_odata(_list_path(filters, top=top, skip=skip, with_parts=False)).get("value") or []) if isinstance(row, dict)]
    rows = [_row_view(row) for row in raw if not is_secret(row)]
    return {
        "summary": f"Протоколы: {len(rows)}",
        "rows": rows,
        "count": len(rows),
        "skip": skip,
        "next_skip": skip + len(raw),
        "has_more": len(raw) >= top,
        "hidden_secret": len(raw) - len(rows),
        "statuses": [{"code": code, "label": label} for code, label in STATUSES.items()],
        "kinds": [{"code": code, "label": label} for code, label in KINDS.items()],
    }


def _date(value: Any) -> str:
    return _text(value)


def _person(key: Any) -> str:
    return _names.get(_text(key), "")


def _plan_rows(items: list[dict[str, Any]], *, text_key: str) -> list[dict[str, Any]]:
    return [
        {
            "n": int(item.get("LineNumber") or 0),
            "text": _text(item.get(text_key)),
            "responsible": _person(item.get("Ответственный_Key")),
            "plan": _text(item.get("План")),
            "fact": _text(item.get("Факт")),
            "deviation": _text(item.get("Отклонение")),
            "unit": _text(item.get("ЕдиницаИзмерения")),
            "comment": _text(item.get("Комментарий")),
            "done": _flag(item.get("Выполнено")),
        }
        for item in items
    ]


def protocol_card(args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("ref_key") or args.get("id") or "").strip()
    if not _GUID_RE.match(ref):
        raise DocflowProtocolError("Нужен Ref_Key протокола")
    # $expand работает только в списке: одиночный GET по guid его не принимает.
    found = _odata(_list_path([f"Ref_Key eq guid'{ref}'"], top=1, skip=0, with_parts=True)).get("value") or []
    row = found[0] if found and isinstance(found[0], dict) else {}
    if not row:
        raise DocflowProtocolError("1С не вернула протокол")
    if is_secret(row):
        raise DocflowProtocolError("Протокол с ограниченным грифом доступа — в Оркестраторе не показывается.")

    def part(name: str) -> list[dict[str, Any]]:
        items = [item for item in (row.get(name) or []) if isinstance(item, dict)]
        items.sort(key=lambda item: int(item.get("LineNumber") or 0))
        return items

    agenda, decisions = part("ПовесткаСовещания"), part("Решения")
    variable, permanent = part("ПеременныеЗадачиПротокола"), part("ПостоянныеЗадачиПротокола")
    period_done, period_plan, plan_fact = (
        part("ВыполнениеЗадачЗаОтчетныйПериод"),
        part("ПланЗадачНаПериод"),
        part("ПланФакт"),
    )
    attendees = part("ПрисутствующиеНаСовещании")
    keys: set[str] = set()
    for items, fields in (
        (agenda, ("Ответственный_Key",)),
        (variable, ("Ответственный_Key", "Автор_Key")),
        (permanent, ("Автор_Key",)),
        (period_done, ("Ответственный_Key",)),
        (period_plan, ("Ответственный_Key",)),
        (plan_fact, ("Ответственный_Key",)),
        (attendees, ("Участник_Key",)),
        (decisions, ("КтоОтменил_Key",)),
    ):
        keys.update(_text(item.get(field)) for item in items for field in fields)
    _resolve_names(keys)

    view = _row_view(row)
    tasks = [
        {
            "n": int(item.get("НомерПунктаПротокола") or item.get("LineNumber") or 0),
            "text": _text(item.get("Задача")),
            "responsible": _person(item.get("Ответственный_Key")),
            "author": _person(item.get("Автор_Key")),
            "set_at": _date(item.get("ДатаПостановкиЗадачи")),
            "done_at": _date(item.get("ДатаФактическогоИсполнения")),
            "priority": _text(item.get("Приоритет")),
            "sent": _flag(item.get("Отправлена")),
            "note": _text(item.get("Примечание")),
            "permanent": False,
        }
        for item in variable
    ] + [
        {
            "n": int(item.get("НомерПунктаПротокола") or item.get("LineNumber") or 0),
            "text": _text(item.get("Задача")),
            "responsible": _text(item.get("Ответственный")),
            "author": _person(item.get("Автор_Key")),
            "set_at": _date(item.get("ДатаПостановкиЗадачи")),
            "done_at": _date(item.get("ДатаФактическогоИсполнения")),
            "priority": _text(item.get("Приоритет")),
            "sent": False,
            "note": _text(item.get("Примечание")),
            "permanent": True,
        }
        for item in permanent
    ]
    decision_rows = [
        {
            "n": int(item.get("LineNumber") or 0),
            "text": _text(item.get("ТекстРешения")),
            "result": _text(item.get("РезультатРешения")),
            "start": _date(item.get("ДатаНачала")),
            "finish": _date(item.get("ДатаОкончания")),
            "done_at": _date(item.get("ДатаИсполнения")),
            "sent": _flag(item.get("Отправлено")),
            "cancelled": _flag(item.get("Отменено")),
            "cancel_reason": _text(item.get("ПричинаОтмены")),
            "cancelled_by": _person(item.get("КтоОтменил_Key")),
        }
        for item in decisions
    ]
    names = [_person(item.get("Участник_Key")) for item in attendees]
    view["participants"] = [name for name in names if name] or view["participants"]
    return {
        "summary": f"Протокол {view['number']}",
        "protocol": view,
        "agenda": [
            {
                "n": int(item.get("LineNumber") or 0),
                "text": _text(item.get("Вопрос")),
                "responsible": _person(item.get("Ответственный_Key")),
                "attachments": _text(item.get("ОтметкаОНаличииПриложений")),
            }
            for item in agenda
        ],
        "decisions": decision_rows,
        "tasks": tasks,
        "period_done": _plan_rows(period_done, text_key="Задача"),
        "period_plan": _plan_rows(period_plan, text_key="Задача"),
        "plan_fact": _plan_rows(plan_fact, text_key="ОтчетОВыполненнойРаботе"),
        "stats": {
            "decisions": len(decision_rows),
            "decisions_done": sum(1 for item in decision_rows if item["done_at"] and not item["cancelled"]),
            "decisions_cancelled": sum(1 for item in decision_rows if item["cancelled"]),
            "tasks": len(tasks),
            "tasks_done": sum(1 for item in tasks if item["done_at"]),
        },
        "loaded_at": datetime.now().isoformat(timespec="seconds"),
    }


def handle_docflow_protocols(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return list_protocols(args)
    except DocflowProtocolError as exc:
        raise OnecToolError(str(exc)) from exc


def handle_docflow_protocol_card(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return protocol_card(args)
    except DocflowProtocolError as exc:
        raise OnecToolError(str(exc)) from exc
