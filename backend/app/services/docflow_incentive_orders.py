"""Журнал приказов о мерах материального стимулирования (депремирование).

Это внутренние документы 1С:Документооборота вида «Приказ о мерах материального
стимулирования», а не документ ERP: в ERP их показывает обработка
ТД_СОМИнтеграцияИБ COM-соединением с базой ДО. Читаем напрямую из ДО тем же
SOAP-сервисом dm.1cws, что и задачи, под учёткой вошедшего пользователя.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.tools.onec.dok_soap import (
    NS,
    DokConfig,
    condition,
    datetime_value,
    execute_dm,
    load_config,
    object_id_value,
    xml_escape,
)

logger = logging.getLogger(__name__)

ENTITY = "DMInternalDocument"
KIND_TYPE = "DMInternalDocumentType"
# Справочник.ВидыВнутреннихДокументов → «Приказ о мерах материального стимулирования».
KIND_ID = "0c0b6059-d4e6-11e7-8267-ac1f6b05524d"
# additionalProperties в columnSet список не отдаёт — сотрудник и процент приходят только в карточке.
_COLUMNS = (
    "regNumber",
    "regDate",
    "status",
    "subdivision",
    "responsible",
    "author",
    "organization",
    "title",
    "summary",
    "comment",
)
_PROPS = {
    "Депремируемый сотрудник": "employee",
    "Подразделение депремируемого": "employee_department",
    "Процент депремирования": "percent",
    "Сумма депремирования": "amount",
    "Период зарплаты": "salary_period",
    "Утверждающий руководитель": "approver",
    "Контролирующий руководитель": "controller",
    "Не выполненная задача": "task",
    "Автор задачи": "task_author",
    "Дисциплинарное взыскание": "discipline",
    "Аннулирован": "cancelled",
    "Причина аннулирования": "cancel_reason",
    "Кем аннулирован": "cancelled_by",
    "Дата аннулирования": "cancelled_at",
}
_TEXT_PROPS = frozenset(
    {
        "employee",
        "employee_department",
        "salary_period",
        "approver",
        "controller",
        "task",
        "task_author",
        "discipline",
        "cancel_reason",
        "cancelled_by",
        "cancelled_at",
    }
)
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_EMPTY_DATE = "0001-01-01"
_PERIOD_LIMIT = 2000
_DEFAULT_PAGE = 40
_MAX_PAGE = 100
_CARD_CHUNK = 50
_LIST_TIMEOUT_SEC = 120.0
_CACHE_TTL_SEC = 300.0

_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_auth_choice: dict[str, int] = {}
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class DocflowIncentiveOrdersError(RuntimeError):
    pass


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def _run(args: dict[str, Any], work: Callable[[DokConfig], Any]) -> Any:
    """ДО принимает то ФИО, то логин сеанса — перебираем варианты и запоминаем рабочий."""
    from app.tools.onec.docflow_inbox_fetch import _is_soap_http_auth_error, _soap_login_attempts

    attempts = _soap_login_attempts(args)
    if not attempts:
        raise DocflowIncentiveOrdersError("Нет пароля 1С с экрана входа. Войдите с паролем 1С.")
    key = attempts[0][0].casefold()
    order = list(range(len(attempts)))
    remembered = _auth_choice.get(key)
    if remembered is not None and remembered < len(attempts):
        order = [remembered] + [index for index in order if index != remembered]
    last = ""
    for index in order:
        username, password = attempts[index]
        try:
            result = work(load_config(username=username, password=password))
        except (RuntimeError, ValueError, OSError) as exc:
            last = str(exc)
            if _is_soap_http_auth_error(last):
                continue
            raise DocflowIncentiveOrdersError(last) from exc
        _auth_choice[key] = index
        return result
    raise DocflowIncentiveOrdersError(last or "Документооборот не принял логин и пароль 1С.")


def _execute(config: DokConfig, request_xml: str, *, timeout: float) -> ET.Element:
    try:
        return execute_dm(config, request_xml, timeout=timeout)
    except (RuntimeError, ValueError, OSError) as exc:
        raise DocflowIncentiveOrdersError(str(exc)) from exc


def _tag(node: ET.Element) -> str:
    return node.tag.split("}")[-1]


def _clean(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return "" if text.startswith(_EMPTY_DATE) else text


def _number(value: Any) -> float:
    try:
        return round(float(str(value or "0").replace(",", ".")), 2)
    except (TypeError, ValueError):
        return 0.0


def _flag(value: Any) -> bool:
    return str(value or "").strip().lower() == "true"


def _child_text(node: ET.Element, tag: str) -> str:
    for child in node:
        if _tag(child) == tag:
            return _clean(child.text)
    return ""


def _field(obj: ET.Element, tag: str) -> str:
    """Реквизит документа: простое значение или имя ссылки."""
    for child in obj:
        if _tag(child) != tag:
            continue
        direct = _clean(child.text)
        return direct or _child_text(child, "name")
    return ""


def _object_id(obj: ET.Element) -> str:
    for child in obj:
        if _tag(child) != "objectID":
            continue
        return _child_text(child, "id")
    return ""


def _base_row(obj: ET.Element) -> dict[str, Any]:
    return {
        "id": _object_id(obj),
        "number": _field(obj, "regNumber"),
        "date": _field(obj, "regDate"),
        "status": _field(obj, "status"),
        "organization": _field(obj, "organization"),
        "department": _field(obj, "subdivision"),
        "responsible": _field(obj, "responsible"),
        "author": _field(obj, "author"),
        "title": _field(obj, "title") or _field(obj, "name"),
        "summary": _field(obj, "summary"),
        "comment": _field(obj, "comment"),
        "employee": "",
        "employee_department": "",
        "percent": 0.0,
        "amount": 0.0,
        "salary_period": "",
        "approver": "",
        "controller": "",
        "task": "",
        "task_author": "",
        "discipline": "",
        "cancelled": False,
        "cancel_reason": "",
        "cancelled_by": "",
        "cancelled_at": "",
    }


def _apply_properties(row: dict[str, Any], obj: ET.Element) -> None:
    for node in obj:
        if _tag(node) != "additionalProperties":
            continue
        key = _PROPS.get(_child_text(node, "name"))
        if not key:
            continue
        value = ""
        for child in node:
            tag = _tag(child)
            if tag == "propertySimpleValue":
                value = _clean(child.text)
            elif tag == "propertyObjectValue":
                value = _child_text(child, "name")
        if key in _TEXT_PROPS:
            row[key] = value
        elif key == "cancelled":
            row[key] = _flag(value)
        else:
            row[key] = _number(value)


def _day_bounds(raw: Any, *, end: bool) -> datetime | None:
    text = str(raw or "").strip()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    stamp = datetime.strptime(text, "%Y-%m-%d")
    return stamp.replace(hour=23, minute=59, second=59) if end else stamp


def _objects(root: ET.Element) -> list[ET.Element]:
    found = root.findall(".//m:items/m:object", NS)
    return found or root.findall(".//m:objects", NS)


def _period_rows(
    config: DokConfig,
    start: datetime | None,
    finish: datetime | None,
) -> list[dict[str, Any]]:
    """Весь период разом: у запроса ДО нет смещения, страницы режем уже у себя."""
    filters = [condition("documentType", object_id_value(KIND_ID, KIND_TYPE))]
    if start:
        filters.append(condition("regDate", datetime_value(start), ">="))
    if finish:
        filters.append(condition("regDate", datetime_value(finish), "<="))
    root = _execute(
        config,
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        f"<dm:type>{ENTITY}</dm:type>"
        "<dm:query>"
        + "".join(filters)
        + f"<dm:limit>{_PERIOD_LIMIT}</dm:limit>"
        + "".join(f"<dm:columnSet>{name}</dm:columnSet>" for name in _COLUMNS)
        + "</dm:query>"
        "</dm:request>",
        timeout=_LIST_TIMEOUT_SEC,
    )
    rows = [_base_row(obj) for obj in _objects(root)]
    rows = [row for row in rows if row["id"]]
    rows.sort(key=lambda row: row["date"], reverse=True)
    return rows


def _cached_period_rows(config: DokConfig, start: datetime | None, finish: datetime | None) -> list[dict[str, Any]]:
    key = f"{config.user}|{start:%Y-%m-%d}|{finish:%Y-%m-%d}" if start and finish else f"{config.user}|all"
    with _lock_for(key):
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < _CACHE_TTL_SEC:
            return hit[1]
        rows = _period_rows(config, start, finish)
        _cache[key] = (time.time(), rows)
        return rows


def _fill_cards(config: DokConfig, rows: list[dict[str, Any]]) -> None:
    """Сотрудник, процент и сумма живут в доп. реквизитах — их отдаёт только карточка."""
    for index in range(0, len(rows), _CARD_CHUNK):
        chunk = rows[index : index + _CARD_CHUNK]
        ids_xml = "".join(
            f"<dm:objectIds><dm:id>{xml_escape(row['id'])}</dm:id><dm:type>{ENTITY}</dm:type></dm:objectIds>"
            for row in chunk
        )
        root = _execute(
            config,
            f'<dm:request xsi:type="dm:DMRetrieveRequest">{ids_xml}</dm:request>',
            timeout=_LIST_TIMEOUT_SEC,
        )
        cards = {}
        for obj in root.iter():
            if _tag(obj) != "objects":
                continue
            ident = _object_id(obj)
            if ident:
                cards[ident] = obj
        for row in chunk:
            card = cards.get(row["id"])
            if card is not None:
                _apply_properties(row, card)


def _status_options(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    names = sorted({row["status"] for row in rows if row["status"]})
    return [{"code": name, "label": name} for name in names]


def list_incentive_orders(args: dict[str, Any]) -> dict[str, Any]:
    top = max(1, min(int(args.get("top") or _DEFAULT_PAGE), _MAX_PAGE))
    skip = max(0, int(args.get("skip") or 0))
    start = _day_bounds(args.get("date_from"), end=False)
    finish = _day_bounds(args.get("date_to"), end=True)
    status = str(args.get("status") or "").strip()

    def work(config: DokConfig) -> dict[str, Any]:
        period = _cached_period_rows(config, start, finish)
        listed = [row for row in period if not status or row["status"] == status]
        page = [dict(row) for row in listed[skip : skip + top]]
        _fill_cards(config, page)
        return {
            "summary": f"Приказы о мерах материального стимулирования: {len(page)} из {len(listed)}",
            "rows": page,
            "count": len(page),
            "total": len(listed),
            "skip": skip,
            "next_skip": skip + len(page),
            "has_more": skip + len(page) < len(listed),
            "statuses": _status_options(period),
        }

    return _run(args, work)


def incentive_order_card(args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("ref_key") or args.get("id") or "").strip()
    if not _GUID_RE.match(ref):
        raise DocflowIncentiveOrdersError("Нужен идентификатор приказа")

    def work(config: DokConfig) -> dict[str, Any]:
        root = _execute(
            config,
            '<dm:request xsi:type="dm:DMRetrieveRequest">'
            f"<dm:objectIds><dm:id>{xml_escape(ref)}</dm:id><dm:type>{ENTITY}</dm:type></dm:objectIds>"
            "</dm:request>",
            timeout=_LIST_TIMEOUT_SEC,
        )
        card = next((obj for obj in root.iter() if _tag(obj) == "objects"), None)
        if card is None:
            raise DocflowIncentiveOrdersError("Документооборот не вернул приказ")
        row = _base_row(card)
        _apply_properties(row, card)
        return {
            "summary": f"Приказ о мерах материального стимулирования {row['number']}",
            "order": row,
            "loaded_at": datetime.now().isoformat(timespec="seconds"),
        }

    return _run(args, work)


def handle_docflow_incentive_orders(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return list_incentive_orders(args)
    except DocflowIncentiveOrdersError as exc:
        raise OnecToolError(str(exc)) from exc


def handle_docflow_incentive_order_card(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    from app.services.onec_tools import OnecToolError

    try:
        return incentive_order_card(args)
    except DocflowIncentiveOrdersError as exc:
        raise OnecToolError(str(exc)) from exc
