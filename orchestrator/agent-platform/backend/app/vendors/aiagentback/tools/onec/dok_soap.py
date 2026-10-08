"""SOAP-клиент 1С:Документооборот (DMService 2.1).

``TasksII/User`` отдаёт таблицу исполнений документов и для inbox-задач
пустой. Список «Мои задачи» берём из ``DMGetObjectListRequest``
(``DMBusinessProcessTask``): отбор по исполнителю в XDTO нет, поэтому
снимаем невыполненные за окно дат и фильтруем ``performer`` на клиенте.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET

import requests

from app.vendors.aiagentback.core.config import settings
from app.vendors.aiagentback.core.logging import get_logger
from app.vendors.aiagentback.tools.onec.dok_http import _decode_dok_body, _dok_auth_headers, dok_http_configured

logger = get_logger(__name__)

DM_NS = "http://www.1c.ru/dm"
_NS = {"m": DM_NS}
_SOAP_ACTION = "http://www.1c.ru/dm#DMService:execute"
_EMPTY_DATE_PREFIX = "0001-01-01"


def dok_soap_url() -> str:
    server = str(settings.DOK_HTTP_SERVER or "").strip()
    port = int(settings.DOK_HTTP_PORT or 81)
    base = str(settings.DOK_HTTP_BASE_PATH or "").rstrip("/")
    return f"http://{server}:{port}{base}/ws/dm.1cws"


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _envelope(request_xml: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" '
        f'xmlns:dm="{DM_NS}" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'xmlns:xs="http://www.w3.org/2001/XMLSchema">'
        "<soap:Body><dm:execute>"
        f"{request_xml}"
        "</dm:execute></soap:Body></soap:Envelope>"
    )


def _condition(property_name: str, value_xml: str, operator: str | None = None) -> str:
    op_xml = (
        f"<dm:comparisonOperator>{_xml_escape(operator)}</dm:comparisonOperator>"
        if operator
        else ""
    )
    return (
        "<dm:conditions>"
        f"<dm:property>{_xml_escape(property_name)}</dm:property>"
        f"{value_xml}"
        f"{op_xml}"
        "</dm:conditions>"
    )


def _object_id_value(object_id: str, type_name: str) -> str:
    return (
        '<dm:value xsi:type="dm:DMObjectID">'
        f"<dm:id>{_xml_escape(object_id)}</dm:id>"
        f"<dm:type>{_xml_escape(type_name)}</dm:type>"
        "</dm:value>"
    )


def _string_value(value: str) -> str:
    return f'<dm:value xsi:type="xs:string">{_xml_escape(value)}</dm:value>'


def _bool_value(value: bool) -> str:
    return f'<dm:value xsi:type="xs:boolean">{"true" if value else "false"}</dm:value>'


def _datetime_value(value: datetime) -> str:
    return f'<dm:value xsi:type="xs:dateTime">{value.strftime("%Y-%m-%dT%H:%M:%S")}</dm:value>'


def execute_dm_request(request_xml: str, *, timeout: float | None = None) -> ET.Element:
    if not dok_http_configured():
        raise RuntimeError("DOK_HTTP_SERVER / DOK_HTTP_USER не заданы")

    response = requests.post(
        dok_soap_url(),
        headers={
            **_dok_auth_headers(),
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": _SOAP_ACTION,
        },
        data=_envelope(request_xml).encode("utf-8"),
        timeout=float(timeout or settings.DOK_HTTP_TIMEOUT or 30),
    )
    text = _decode_dok_body(response.content)
    if response.status_code > 299:
        raise RuntimeError(f"HTTP {response.status_code}: {text[:800]}")
    root = ET.fromstring(text)
    error = root.find(".//m:return[@{http://www.w3.org/2001/XMLSchema-instance}type='m:DMError']", _NS)
    if error is None:
        for node in root.findall(".//m:return", _NS):
            type_name = node.attrib.get("{http://www.w3.org/2001/XMLSchema-instance}type", "")
            if type_name.endswith("DMError"):
                error = node
                break
    if error is not None:
        subject = error.findtext("m:subject", default="", namespaces=_NS)
        description = error.findtext("m:description", default="", namespaces=_NS)
        raise RuntimeError(f"{subject}: {description}".strip(": "))
    fault = root.find(".//{http://schemas.xmlsoap.org/soap/envelope/}Fault")
    if fault is not None:
        raise RuntimeError(fault.findtext("faultstring") or text[:800])
    return root


def _text(node: ET.Element | None, path: str) -> str:
    if node is None:
        return ""
    found = node.find(path, _NS)
    return (found.text or "").strip() if found is not None else ""


def parse_dm_users(root: ET.Element) -> list[dict[str, str]]:
    users: list[dict[str, str]] = []
    for item in root.findall(".//m:items", _NS):
        obj = item.find("m:object", _NS)
        if obj is None:
            continue
        users.append(
            {
                "name": _text(obj, "m:name"),
                "id": _text(obj, "m:objectID/m:id"),
                "type": _text(obj, "m:objectID/m:type") or "DMUser",
            }
        )
    return [user for user in users if user["id"]]


def parse_dm_tasks(root: ET.Element) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    objects = list(root.findall(".//m:items/m:object", _NS))
    if not objects:
        objects = list(root.findall(".//m:objects", _NS))
    for obj in objects:
        due = _text(obj, "m:dueDate")
        rows.append(
            {
                "name": _text(obj, "m:name"),
                "id": _text(obj, "m:objectID/m:id"),
                "performer": _text(obj, "m:performer/m:user/m:name") or _text(obj, "m:performer/m:name"),
                "author": _text(obj, "m:author/m:name"),
                "begin": _text(obj, "m:beginDate"),
                "due": "" if due.startswith(_EMPTY_DATE_PREFIX) else due,
                "executed": _text(obj, "m:executed") == "true",
                "step": _text(obj, "m:businessProcessStep"),
                "number": _text(obj, "m:number"),
                "description": _text(obj, "m:description"),
                "target": _text(obj, "m:target/m:name"),
                "target_id": _text(obj, "m:target/m:objectID/m:id"),
                "state": _text(obj, "m:state/m:name"),
            }
        )
    return [row for row in rows if row["id"]]


def find_do_user(name: str) -> dict[str, str]:
    fio = str(name or "").strip()
    if not fio:
        raise ValueError("Пустое ФИО пользователя ДО")
    root = execute_dm_request(
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        "<dm:type>DMUser</dm:type>"
        "<dm:query>"
        f"{_condition('name', _string_value(fio))}"
        "<dm:limit>5</dm:limit>"
        "</dm:query>"
        "</dm:request>"
    )
    users = parse_dm_users(root)
    if not users:
        raise ValueError(f"Пользователь ДО не найден: «{fio}»")
    return users[0]


def list_open_tasks_since(since: datetime, *, timeout: float = 180) -> list[dict[str, Any]]:
    root = execute_dm_request(
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        "<dm:type>DMBusinessProcessTask</dm:type>"
        "<dm:query>"
        f"{_condition('beginDate', _datetime_value(since), '>=')}"
        f"{_condition('withExecuted', _bool_value(False))}"
        "<dm:limit>500</dm:limit>"
        "<dm:columnSet>name</dm:columnSet>"
        "<dm:columnSet>performer</dm:columnSet>"
        "<dm:columnSet>author</dm:columnSet>"
        "<dm:columnSet>beginDate</dm:columnSet>"
        "<dm:columnSet>dueDate</dm:columnSet>"
        "<dm:columnSet>executed</dm:columnSet>"
        "<dm:columnSet>description</dm:columnSet>"
        "<dm:columnSet>target</dm:columnSet>"
        "</dm:query>"
        "</dm:request>",
        timeout=timeout,
    )
    return [row for row in parse_dm_tasks(root) if not row["executed"]]


def retrieve_tasks(task_ids: list[str], *, timeout: float = 60) -> list[dict[str, Any]]:
    if not task_ids:
        return []
    ids_xml = "".join(
        "<dm:objectIds>"
        f"<dm:id>{_xml_escape(task_id)}</dm:id>"
        "<dm:type>DMBusinessProcessTask</dm:type>"
        "</dm:objectIds>"
        for task_id in task_ids
    )
    root = execute_dm_request(
        f'<dm:request xsi:type="dm:DMRetrieveRequest">{ids_xml}</dm:request>',
        timeout=timeout,
    )
    return parse_dm_tasks(root)


def _normalize_person(value: str) -> str:
    return " ".join(value.lower().replace("ё", "е").split())


def fetch_user_inbox_tasks(
    user_fio: str,
    *,
    since_days: int = 90,
    enrich: bool = True,
) -> dict[str, Any]:
    """Невыполненные задачи исполнителя из ДО (inbox, не таблица исполнений)."""

    user = find_do_user(user_fio)
    since = datetime.now() - timedelta(days=max(int(since_days), 1))
    timeout = max(float(settings.DOK_HTTP_TIMEOUT or 30), 180)
    rows = [
        row
        for row in list_open_tasks_since(since, timeout=timeout)
        if _normalize_person(str(row.get("performer") or ""))
        == _normalize_person(user["name"])
    ]
    if enrich and rows:
        details = {row["id"]: row for row in retrieve_tasks([row["id"] for row in rows])}
        rows = [details.get(row["id"], row) for row in rows]
    return {
        "endpoint": dok_soap_url(),
        "user_ref": user["id"],
        "user_fio": user["name"],
        "since": since.strftime("%Y-%m-%d"),
        "count": len(rows),
        "rows": rows,
    }
