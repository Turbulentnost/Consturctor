"""Создание бизнес-процессов 1С:Документооборот по документу-основанию (SOAP DMService).

Задачу в ДО нельзя создать отдельно: её выпускает бизнес-процесс, запущенный
по документу-предмету. Цепочка запросов:
  DMGetNewBusinessProcessRequest (заготовка по предмету) → заполнение → DMLaunchBusinessProcessRequest.
XDTO проверяет порядок элементов по схеме, поэтому поля вставляются по спискам ниже.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from app.tools.onec.dok_soap import (
    DM_NS,
    NS,
    XSI_TYPE,
    DokConfig,
    _cache_dir,
    _object_xml,
    condition,
    datetime_value,
    execute_dm,
    object_id_value,
    string_value,
    xml_escape,
    xml_text,
)

logger = logging.getLogger(__name__)

_OBJECT_ORDER = ["name", "objectID", "externalObject", "externalObjects"]
_PROCESS_ORDER = _OBJECT_ORDER + [
    "author",
    "importance",
    "beginDate",
    "endDate",
    "tasks",
    "target",
    "started",
    "completed",
    "completionMark",
    "description",
    "dueDate",
    "parentTask",
    "state",
    "dueTimeEnabled",
    "parentTaskEnabled",
    "stateEnabled",
    "businessProcessTemplate",
    "project",
    "executionComment",
    "blockedByTemplate",
    "targets",
    "dueDateSpecificationOption",
    "dueDateDays",
    "dueDateHours",
    "dueDateMinutes",
    "leadingTask",
    "leadingTaskEnabled",
    "TD_NewDateExecution",
    "TD_OldDateExecution",
    "TD_ReasonForPostponement",
]
PROCESS_FIELD_ORDER: dict[str, list[str]] = {
    "DMBusinessProcessPerformance": _PROCESS_ORDER
    + ["controller", "verifier", "performers", "performanceType", "currentIteration"],
    "DMBusinessProcessAcquaintance": _PROCESS_ORDER + ["performers"],
    "DMBusinessProcessConsideration": _PROCESS_ORDER
    + [
        "performer",
        "resolution",
        "resultProcessingDueDateSpecificationOption",
        "resultProcessingDueDate",
        "resultProcessingDueDateDays",
        "resultProcessingDueDateHours",
        "resultProcessingDueDateMinutes",
    ],
}
# Порядок из живого процесса ДО: свои поля участника идут до унаследованных (user, срок).
_PARTICIPANT_ORDER = [
    "personalDueDate",
    "personalDescription",
    "personalTaskName",
    "task",
    "responsible",
    "performanceOrder",
    "passed",
    "user",
    "role",
    "mainAddressingObject",
    "secondaryAddressingObject",
    "dueDateSpecificationOption",
    "dueDate",
    "dueDateDays",
    "dueDateHours",
    "dueDateMinutes",
]
_XSI_NIL = "{http://www.w3.org/2001/XMLSchema-instance}nil"
_TYPES_TTL_SEC = 3600.0
_types_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}


def _tag(name: str) -> str:
    return f"{{{DM_NS}}}{name}"


def _local(tag: str) -> str:
    return tag.split("}")[-1]


def soap_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def end_of_day(value: datetime) -> datetime:
    return value.replace(hour=23, minute=59, second=59, microsecond=0)


def user_element(tag: str, user: dict[str, str]) -> ET.Element:
    """DMUser внутри исполнителя: name обязателен и идёт перед objectID."""
    node = ET.Element(_tag(tag))
    ET.SubElement(node, _tag("name")).text = user.get("name") or ""
    object_id = ET.SubElement(node, _tag("objectID"))
    ET.SubElement(object_id, _tag("id")).text = user.get("id") or ""
    ET.SubElement(object_id, _tag("type")).text = user.get("type") or "DMUser"
    return node


def executor_element(tag: str, user: dict[str, str]) -> ET.Element:
    """DMBusinessProcessTaskExecutor: исполнитель задаётся пользователем."""
    node = ET.Element(_tag(tag))
    node.append(user_element("user", user))
    return node


def set_child(node: ET.Element, name: str, order: list[str], value: str | ET.Element) -> ET.Element:
    """Заменить или вставить дочерний элемент, соблюдая порядок последовательности XSD."""
    for existing in [child for child in node if _local(child.tag) == name]:
        node.remove(existing)
    if isinstance(value, ET.Element):
        child = value
        child.tag = _tag(name)
    else:
        child = ET.Element(_tag(name))
        child.text = value
    _insert_ordered(node, child, order)
    return child


def replace_children(node: ET.Element, name: str, order: list[str], values: list[ET.Element]) -> None:
    for existing in [child for child in node if _local(child.tag) == name]:
        node.remove(existing)
    for value in values:
        value.tag = _tag(name)
        _insert_ordered(node, value, order)


def _insert_ordered(node: ET.Element, child: ET.Element, order: list[str]) -> None:
    name = _local(child.tag)
    rank = order.index(name) if name in order else len(order)
    children = list(node)
    for index, existing in enumerate(children):
        existing_name = _local(existing.tag)
        existing_rank = order.index(existing_name) if existing_name in order else len(order)
        if existing_rank > rank:
            node.insert(index, child)
            return
    node.append(child)


def performance_participant(
    user: dict[str, str],
    *,
    due: datetime | None,
    note: str,
    task_name: str,
    responsible: bool,
    template: ET.Element | None = None,
) -> ET.Element:
    """Участник «Исполнения». Если есть образец из живого процесса, повторяем его структуру."""
    # Задача, отметка «пройден» и сроки образца относятся к чужому процессу.
    stale_fields = {"task", "passed", "user", "dueDate", "dueDateDays", "dueDateHours", "dueDateMinutes"}
    if template is not None:
        node = copy.deepcopy(template)
        for stale in [child for child in node if _local(child.tag) in stale_fields]:
            node.remove(stale)
    else:
        node = ET.Element(_tag("performers"))
    _insert_ordered(node, user_element("user", user), _PARTICIPANT_ORDER)
    due_text = soap_datetime(due) if due else ""
    personal_due = set_child(node, "personalDueDate", _PARTICIPANT_ORDER, due_text)
    if due:
        set_child(node, "dueDate", _PARTICIPANT_ORDER, due_text)
    else:
        personal_due.set(_XSI_NIL, "true")
    set_child(node, "personalDescription", _PARTICIPANT_ORDER, note)
    set_child(node, "personalTaskName", _PARTICIPANT_ORDER, task_name)
    set_child(node, "responsible", _PARTICIPANT_ORDER, "true" if responsible else "false")
    return node


def _save_debug(name: str, text: str) -> None:
    try:
        path: Path = _cache_dir() / name
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        logger.warning("dok_create: не удалось сохранить %s: %s", name, exc)


def list_internal_document_types(config: DokConfig, *, timeout: float) -> list[dict[str, str]]:
    key = f"{config.server}:{config.port}{config.base_path}"
    hit = _types_cache.get(key)
    if hit and time.time() - hit[0] < _TYPES_TTL_SEC:
        return hit[1]
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        "<dm:type>DMInternalDocumentType</dm:type>"
        # columnSet здесь не передаём: для видов документов ДО не знает поля name.
        "<dm:query><dm:limit>500</dm:limit></dm:query>"
        "</dm:request>",
        timeout=timeout,
    )
    types: list[dict[str, str]] = []
    for obj in root.findall(".//m:items/m:object", NS):
        type_id = xml_text(obj, "m:objectID/m:id")
        name = xml_text(obj, "m:name")
        if type_id and name:
            types.append({"id": type_id, "name": name})
    types.sort(key=lambda item: item["name"].casefold())
    _types_cache[key] = (time.time(), types)
    return types


def list_users(config: DokConfig, *, timeout: float) -> list[str]:
    """Все пользователи ДО — ровно те, кому можно поставить задачу."""
    key = f"users:{config.server}:{config.port}{config.base_path}"
    hit = _types_cache.get(key)
    if hit and time.time() - hit[0] < _TYPES_TTL_SEC:
        return [item["name"] for item in hit[1]]
    started = time.perf_counter()
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        "<dm:type>DMUser</dm:type>"
        "<dm:query><dm:limit>20000</dm:limit></dm:query>"
        "</dm:request>",
        timeout=timeout,
    )
    names = sorted(
        {xml_text(obj, "m:name") for obj in root.findall(".//m:items/m:object", NS)} - {""},
        key=str.casefold,
    )
    _types_cache[key] = (time.time(), [{"id": "", "name": name} for name in names])
    logger.info("dok_create: пользователей ДО %s за %.1f с", len(names), time.perf_counter() - started)
    return names


_NAME_DATE = re.compile(r"\bот\s+(\d{2})\.(\d{2})\.(\d{4})")


def document_day(obj: ET.Element) -> str:
    """Дата документа: регистрации, а у незарегистрированных — «от ДД.ММ.ГГГГ» из названия."""
    reg = xml_text(obj, "m:regDate")[:10]
    if reg and not reg.startswith("0001"):
        return reg
    for text in (xml_text(obj, "m:name"), xml_text(obj, "m:title")):
        match = _NAME_DATE.search(text)
        if match:
            return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"
    return ""


def parse_approval_sheet(root: ET.Element) -> list[dict[str, str]]:
    """Строки листа согласования из DMGetApprovalSheetResponse."""
    items: list[dict[str, str]] = []
    for node in root.findall(".//m:items", NS):
        name = xml_text(node, "m:name")
        position = xml_text(node, "m:position")
        if not name and not position:
            continue
        raw_date = xml_text(node, "m:date")
        if raw_date.startswith("0001"):
            raw_date = ""
        items.append(
            {
                "name": name,
                "position": position,
                "date": raw_date[:10],
                "result": xml_text(node, "m:result"),
                "comment": xml_text(node, "m:comment"),
            }
        )
    return items


def fetch_approval_sheet(
    config: DokConfig,
    object_id: str,
    object_type: str,
    *,
    name: str = "",
    timeout: float,
) -> list[dict[str, str]]:
    """Лист согласования документа ДО: кто согласовывал, должность, дата и результат."""
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMGetApprovalSheetRequest">'
        "<dm:object>"
        f"<dm:name>{xml_escape(name)}</dm:name>"
        "<dm:objectID>"
        f"<dm:id>{xml_escape(object_id)}</dm:id>"
        f"<dm:type>{xml_escape(object_type or 'DMInternalDocument')}</dm:type>"
        "</dm:objectID>"
        "</dm:object>"
        "</dm:request>",
        timeout=timeout,
    )
    return parse_approval_sheet(root)


def document_row(obj: ET.Element) -> dict[str, str]:
    return {
        "id": xml_text(obj, "m:objectID/m:id"),
        "type": xml_text(obj, "m:objectID/m:type"),
        "name": xml_text(obj, "m:name"),
        "title": xml_text(obj, "m:title"),
        "reg_number": xml_text(obj, "m:regNumber"),
        "reg_date": document_day(obj),
        "author": xml_text(obj, "m:author/m:name") or xml_text(obj, "m:responsible/m:name"),
        "document_type": xml_text(obj, "m:documentType/m:name"),
        "summary": xml_text(obj, "m:summary"),
    }


def search_documents(
    config: DokConfig,
    dm_type: str,
    *,
    document_type_id: str = "",
    author: dict[str, str] | None = None,
    author_field: str = "author",
    query: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 200,
    timeout: float,
) -> list[dict[str, str]]:
    """Документы-основания. Условия, которые база не примет, отбрасываем и фильтруем сами.

    columnSet не передаём: для документов ДО отвечает «Поле объекта не обнаружено (name)».
    """
    text = query.strip()
    kind_filter = (
        [condition("documentType", object_id_value(document_type_id, "DMInternalDocumentType"))]
        if document_type_id
        else []
    )
    period: list[str] = []
    if date_from:
        period.append(condition("regDate", datetime_value(date_from), ">="))
    if date_to:
        period.append(condition("regDate", datetime_value(date_to), "<="))
    others: list[str] = []
    if author and author.get("id"):
        others.append(condition(author_field, object_id_value(author["id"], author.get("type") or "DMUser")))
    if text:
        others.append(condition("title", string_value(f"%{text}%"), "LIKE"))

    def run(filters: list[str]) -> list[dict[str, str]]:
        root = execute_dm(
            config,
            '<dm:request xsi:type="dm:DMGetObjectListRequest">'
            f"<dm:type>{xml_escape(dm_type)}</dm:type>"
            "<dm:query>"
            f"{''.join(filters)}"
            f"<dm:limit>{max(1, min(int(limit), 500))}</dm:limit>"
            "</dm:query>"
            "</dm:request>",
            timeout=timeout,
        )
        return [row for row in map(document_row, root.findall(".//m:items/m:object", NS)) if row["id"]]

    # От строгого к простому: период отбрасываем последним, без него ДО отдаёт самые старые документы.
    attempts = [kind_filter + period + others, kind_filter + period, kind_filter]
    started = time.perf_counter()
    rows: list[dict[str, str]] = []
    last_error: RuntimeError | None = None
    for filters in dict.fromkeys(tuple(item) for item in attempts):
        try:
            rows = run(list(filters))
            break
        except RuntimeError as exc:
            last_error = exc
            logger.warning(
                "dok_create: поиск %s (условий=%s) не принят: %s", dm_type, len(filters), str(exc)[:200]
            )
    else:
        raise last_error or RuntimeError("Документооборот не вернул документы")
    needle = text.casefold()
    author_name = (author or {}).get("name", "").casefold()
    day_from = date_from.strftime("%Y-%m-%d") if date_from else ""
    day_to = date_to.strftime("%Y-%m-%d") if date_to else ""
    filtered = [
        row
        for row in rows
        if (not needle or needle in f"{row['title']} {row['name']} {row['reg_number']}".casefold())
        and (not author_name or not row["author"] or row["author"].casefold() == author_name)
        and (not day_from or (row["reg_date"] and row["reg_date"] >= day_from))
        and (not day_to or (row["reg_date"] and row["reg_date"] <= day_to))
    ]
    filtered.sort(key=lambda row: row["reg_date"] or "", reverse=True)
    logger.info(
        "dok_create: поиск %s за %.1f с, получено=%s, после фильтра=%s",
        dm_type,
        time.perf_counter() - started,
        len(rows),
        len(filtered),
    )
    return filtered[:limit]


def new_business_process(
    config: DokConfig,
    process_type: str,
    target: dict[str, str],
    *,
    timeout: float,
) -> ET.Element:
    """Заготовка процесса по предмету: ДО сам заполняет автора, важность, предмет и название."""
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMGetNewBusinessProcessRequest">'
        f"<dm:type>{xml_escape(process_type)}</dm:type>"
        "<dm:targetID>"
        f"<dm:id>{xml_escape(target['id'])}</dm:id>"
        f"<dm:type>{xml_escape(target['type'])}</dm:type>"
        "</dm:targetID>"
        "</dm:request>",
        timeout=timeout,
    )
    node = root.find(".//m:object", NS)
    if node is None:
        raise RuntimeError("Документооборот не вернул заготовку процесса")
    if not node.attrib.get(XSI_TYPE):
        node.set(XSI_TYPE, f"dm:{process_type}")
    _save_debug(f"dm_new_{process_type}.xml", ET.tostring(node, encoding="unicode"))
    return node


def sample_performer(
    config: DokConfig,
    process_type: str,
    task_ids: list[str],
    *,
    timeout: float,
) -> ET.Element | None:
    """Образец участника из уже запущенного процесса того же вида.

    Схема WSDL для участника «Исполнения» неполная, поэтому структуру берём у живого процесса.
    Найденный образец сохраняется и дальше читается с диска.
    """
    saved = _cache_dir() / f"dm_sample_{process_type}.xml"
    if saved.is_file():
        try:
            performer = ET.fromstring(saved.read_text(encoding="utf-8")).find("m:performers", NS)
        except (OSError, ET.ParseError) as exc:
            logger.warning("dok_create: сохранённый образец %s не читается: %s", saved.name, exc)
            performer = None
        if performer is not None:
            return copy.deepcopy(performer)
    parents: list[str] = []
    for task_id in task_ids[:20]:
        try:
            root = execute_dm(
                config,
                '<dm:request xsi:type="dm:DMRetrieveRequest">'
                f"<dm:objectIds><dm:id>{xml_escape(task_id)}</dm:id>"
                "<dm:type>DMBusinessProcessTask</dm:type></dm:objectIds>"
                "</dm:request>",
                timeout=timeout,
            )
        except RuntimeError as exc:
            logger.info("dok_create: задача %s для образца не прочитана: %s", task_id, str(exc)[:160])
            continue
        parent = root.find(".//m:parentBusinessProcess", NS)
        parent_type = xml_text(parent, "m:objectID/m:type") if parent is not None else ""
        parents.append(parent_type or "—")
        if parent_type != process_type:
            continue
        process_id = xml_text(parent, "m:objectID/m:id")
        try:
            process_root = execute_dm(
                config,
                '<dm:request xsi:type="dm:DMRetrieveRequest">'
                f"<dm:objectIds><dm:id>{xml_escape(process_id)}</dm:id>"
                f"<dm:type>{xml_escape(process_type)}</dm:type></dm:objectIds>"
                "</dm:request>",
                timeout=timeout,
            )
        except RuntimeError as exc:
            logger.info("dok_create: процесс %s для образца не прочитан: %s", process_id, str(exc)[:160])
            continue
        process = process_root.find(".//m:objects", NS)
        performer = process.find("m:performers", NS) if process is not None else None
        if performer is not None:
            _save_debug(saved.name, ET.tostring(process, encoding="unicode"))
            return copy.deepcopy(performer)
    logger.info(
        "dok_create: образец %s не найден, задач проверено=%s, процессы: %s",
        process_type,
        len(parents),
        ", ".join(sorted(set(parents))) or "—",
    )
    return None


def open_task_ids_by_step(step_pattern: str, *, limit: int = 20) -> list[str]:
    """УИДы открытых задач из выгрузки ДО на диске (для поиска образца процесса)."""
    ids: list[str] = []
    for path in sorted(_cache_dir().glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            rows = json.loads(path.read_text(encoding="utf-8")).get("payload", {}).get("rows", [])
        except (OSError, ValueError, AttributeError):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if re.search(step_pattern, str(row.get("step") or ""), flags=re.I) and row.get("id"):
                ids.append(str(row["id"]))
                if len(ids) >= limit:
                    return ids
    return ids


def fill_process(
    node: ET.Element,
    process_type: str,
    *,
    title: str,
    description: str,
    due: datetime | None,
    performers: list[dict[str, Any]],
    verifier: dict[str, str] | None = None,
    performer_template: ET.Element | None = None,
    priority: str = "",
) -> ET.Element:
    """Заполнить заготовку процесса полями формы. Сроки приходят уже со временем (parse_due)."""
    order = PROCESS_FIELD_ORDER[process_type]
    if title:
        set_child(node, "name", order, title)
    set_child(node, "description", order, description)
    if due is not None:
        set_child(node, "dueDate", order, soap_datetime(due))
    if priority:
        set_importance(node, process_type, priority)
    if process_type == "DMBusinessProcessPerformance":
        if verifier:
            set_child(node, "verifier", order, executor_element("verifier", verifier))
        participants = [
            performance_participant(
                item["user"],
                due=item.get("due") or due,
                note=str(item.get("note") or ""),
                task_name=title,
                # ДО: «Единственный исполнитель не может быть ответственным».
                responsible=index == 0 and len(performers) > 1,
                template=performer_template,
            )
            for index, item in enumerate(performers)
        ]
        replace_children(node, "performers", order, participants)
    elif process_type == "DMBusinessProcessAcquaintance":
        replace_children(
            node,
            "performers",
            order,
            [executor_element("performers", item["user"]) for item in performers],
        )
    elif process_type == "DMBusinessProcessConsideration":
        if len(performers) != 1:
            raise ValueError("Рассмотрение назначается одному сотруднику")
        set_child(node, "performer", order, executor_element("performer", performers[0]["user"]))
    else:
        raise ValueError(f"Процесс {process_type} пока не поддерживается")
    return node


def launch_business_process(config: DokConfig, node: ET.Element, *, timeout: float) -> dict[str, str]:
    request = (
        '<dm:request xsi:type="dm:DMLaunchBusinessProcessRequest">'
        f"{_object_xml(node, tag='businessProcess')}"
        "</dm:request>"
    )
    _save_debug("dm_last_launch_request.xml", request)
    root = execute_dm(config, request, timeout=timeout)
    process = root.find(".//m:businessProcess", NS)
    if process is None:
        raise RuntimeError("Документооборот не вернул запущенный процесс")
    result = {
        "id": xml_text(process, "m:objectID/m:id"),
        "type": xml_text(process, "m:objectID/m:type"),
        "name": xml_text(process, "m:name"),
        "started": xml_text(process, "m:started"),
    }
    logger.info("dok_create: процесс запущен %s", result)
    return result


def parse_due(raw: Any) -> datetime | None:
    """Срок: дата или дата со временем (ГГГГ-ММ-ДДTЧЧ:ММ). Без времени — конец дня."""
    text = str(raw or "").strip()
    if not text:
        return None
    clock = re.search(r"[T ](\d{1,2}):(\d{2})", text)
    hour, minute = (int(clock.group(1)), int(clock.group(2))) if clock else (0, 0)
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", text)
    if match:
        day = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    else:
        match = re.match(r"^(\d{2})\.(\d{2})\.(\d{4})", text)
        if not match:
            raise ValueError(f"Срок в формате ГГГГ-ММ-ДД или ДД.ММ.ГГГГ, получено: {text}")
        day = datetime(int(match.group(3)), int(match.group(2)), int(match.group(1)))
    if not clock:
        return end_of_day(day)
    if hour > 23 or minute > 59:
        raise ValueError(f"Неверное время срока: {text}")
    return day.replace(hour=hour, minute=minute)


IMPORTANCE: dict[str, tuple[str, str]] = {
    "high": ("Высокая", "Высокая важность"),
    "normal": ("Обычная", "Обычная важность"),
    "low": ("Низкая", "Низкая важность"),
}


def set_importance(node: ET.Element, process_type: str, priority: str) -> None:
    """Важность процесса: правим значение в заготовке ДО, тип объекта оставляем как в ней."""
    if priority not in IMPORTANCE:
        raise ValueError(f"Неизвестный приоритет: {priority}")
    value_id, label = IMPORTANCE[priority]
    importance = node.find("m:importance", NS)
    if importance is None:
        importance = ET.Element(_tag("importance"))
        ET.SubElement(importance, _tag("name"))
        object_id = ET.SubElement(importance, _tag("objectID"))
        ET.SubElement(object_id, _tag("id"))
        ET.SubElement(object_id, _tag("type")).text = "DMBusinessProcessTaskImportance"
        _insert_ordered(node, importance, PROCESS_FIELD_ORDER[process_type])
    name = importance.find("m:name", NS)
    if name is not None:
        name.text = label
    object_id = importance.find("m:objectID", NS)
    if object_id is not None:
        for stale in [child for child in object_id if _local(child.tag) in {"presentation", "navigationRef"}]:
            object_id.remove(stale)
        id_node = object_id.find("m:id", NS)
        if id_node is not None:
            id_node.text = value_id


__all__ = [
    "PROCESS_FIELD_ORDER",
    "fill_process",
    "launch_business_process",
    "list_internal_document_types",
    "new_business_process",
    "parse_due",
    "sample_performer",
    "search_documents",
]
