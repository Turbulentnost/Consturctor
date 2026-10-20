"""Возврат задачи 1С:Документооборот на доработку.

Кнопка повторяет штатный возврат «Проверки исполнения» в том же процессе.
Отдельную задачу эта база не создаёт. Документооборот сам выпускает
исполнителю следующую задачу, когда в результате проверки стоят
«возвращено» и комментарий, а у того же исполнителя сдвинут срок.

Так в истории выполнения появляется строка «Задача возвращена на доработку»
с новым сроком и комментарием. Текст самой задачи не подменяется причиной возврата.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from xml.etree import ElementTree as ET

from app.tools.onec.dok_create import (
    PROCESS_FIELD_ORDER,
    _PARTICIPANT_ORDER,
    set_child,
    soap_datetime,
)
from app.tools.onec.dok_soap import (
    NS,
    DokConfig,
    _object_xml,
    _retrieve_task_node,
    execute_dm,
    mark_task_executed,
    open_tasks_for_target,
    xml_text,
)

logger = logging.getLogger(__name__)

_CHECK_RESULT_ORDER = ["executorTask", "returned", "checkComment"]


class ReworkError(RuntimeError):
    pass


def business_process_ref(node: ET.Element) -> tuple[str, str]:
    """Идентификатор и тип реквизита «БизнесПроцесс» (parentBusinessProcess)."""
    for name in ("parentBusinessProcess", "businessProcess"):
        parent = node.find(f"m:{name}", NS)
        process_id = xml_text(parent, "m:objectID/m:id")
        process_type = xml_text(parent, "m:objectID/m:type")
        if process_id:
            return process_id, process_type or "DMBusinessProcessPerformance"
    return "", ""


def _step(node: ET.Element) -> str:
    return " ".join(xml_text(node, "m:businessProcessStep").lower().replace("ё", "е").split())


def _is_check(node: ET.Element) -> bool:
    return "провер" in _step(node) or "контрол" in _step(node)


def _is_execute(node: ET.Element) -> bool:
    return "исполн" in _step(node)


def _performer_task_node(config: DokConfig, source: ET.Element, *, timeout: float) -> ET.Element | None:
    """Задача исполнителя из того же процесса: её копируем, когда возвращаем проверку."""
    process_id, process_type = business_process_ref(source)
    if not process_id:
        return None
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMRetrieveRequest">'
        "<dm:objectIds>"
        f"<dm:id>{process_id}</dm:id>"
        f"<dm:type>{process_type}</dm:type>"
        "</dm:objectIds>"
        "</dm:request>",
        timeout=timeout,
    )
    process = root.find(".//m:objects", NS)
    if process is None:
        return None
    for task in process.findall("m:performers/m:task", NS):
        task_id = xml_text(task, "m:objectID/m:id")
        if not task_id:
            continue
        node = _retrieve_task_node(config, task_id, timeout=timeout)
        if _is_execute(node):
            return node
    return None


def _open_check_task_id(config: DokConfig, source: ET.Element, *, timeout: float) -> str:
    target_id = xml_text(source, "m:target/m:objectID/m:id")
    target_type = xml_text(source, "m:target/m:objectID/m:type")
    if not target_id:
        return ""
    for row in open_tasks_for_target(config, target_id, target_type, timeout=timeout):
        step = " ".join(str(row.get("step") or "").lower().replace("ё", "е").split())
        if "провер" in step or "контрол" in step:
            return str(row.get("id") or "")
    return ""


def checkup_due_comment(due: datetime) -> str:
    """Как в карточке 1С: комментарий проверяющего — новый срок, не свободный текст."""
    return f"Новый срок исполнения: {due.strftime('%d.%m.%Y %H:%M:%S')}"


def apply_checkup_return(checkup: ET.Element, due: datetime) -> None:
    """ОтправленоНаДоработку и комментарий проверяющего в результате проверки."""
    results = checkup.findall("m:checkResults", NS)
    if not results:
        raise ReworkError("У «Проверки исполнения» нет строк результата")
    note = checkup_due_comment(due)
    for result in results:
        set_child(result, "returned", _CHECK_RESULT_ORDER, "true")
        set_child(result, "checkComment", _CHECK_RESULT_ORDER, note)


def shift_performer_due(performer: ET.Element, due: datetime) -> None:
    """Новый срок того же исполнителя. Текст задачи не затирается комментарием."""
    text = soap_datetime(due)
    set_child(performer, "personalDueDate", _PARTICIPANT_ORDER, text)
    set_child(performer, "dueDate", _PARTICIPANT_ORDER, text)


def _select_performer(process: ET.Element, execute_task: ET.Element) -> ET.Element:
    performers = process.findall("m:performers", NS)
    if not performers:
        raise ReworkError("В процессе нет исполнителя, которому возвращается задача")
    task_id = xml_text(execute_task, "m:objectID/m:id")
    user_id = xml_text(execute_task, "m:performer/m:user/m:objectID/m:id") or xml_text(
        execute_task, "m:performer/m:objectID/m:id"
    )
    for item in performers:
        if task_id and xml_text(item, "m:task/m:objectID/m:id") == task_id:
            return item
    for item in performers:
        same_user = user_id and xml_text(item, "m:user/m:objectID/m:id") == user_id
        if same_user and xml_text(item, "m:passed") != "true":
            return item
    for item in performers:
        if user_id and xml_text(item, "m:user/m:objectID/m:id") == user_id:
            return item
    if len(performers) == 1:
        return performers[0]
    raise ReworkError("В процессе несколько исполнителей, и неясно, кому вернуть задачу")


def _shift_process_due(
    config: DokConfig,
    execute_task: ET.Element,
    *,
    due: datetime,
    timeout: float,
) -> None:
    """Сдвигает срок текущего исполнителя. Вторую строку исполнителя не добавляет."""
    process_id, process_type = business_process_ref(execute_task)
    order = PROCESS_FIELD_ORDER.get(process_type)
    if not order:
        raise ReworkError(f"Возврат на доработку пока не умеет процесс {process_type or 'без типа'}")
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMRetrieveRequest">'
        "<dm:objectIds>"
        f"<dm:id>{process_id}</dm:id>"
        f"<dm:type>{process_type}</dm:type>"
        "</dm:objectIds>"
        "</dm:request>",
        timeout=timeout,
    )
    process = root.find(".//m:objects", NS)
    if process is None:
        raise ReworkError("Документооборот не вернул бизнес-процесс")
    shift_performer_due(_select_performer(process, execute_task), due)
    set_child(process, "dueDate", order, soap_datetime(due))
    execute_dm(
        config,
        '<dm:request xsi:type="dm:DMUpdateRequest">'
        f"{_object_xml(process)}"
        "</dm:request>",
        timeout=timeout,
    )


def _save_checkup_return(
    config: DokConfig, checkup_id: str, due: datetime, *, timeout: float
) -> None:
    checkup = _retrieve_task_node(config, checkup_id, timeout=timeout)
    if not _is_check(checkup):
        raise ReworkError("Возврат на доработку закрывает «Проверку исполнения», а не задачу исполнителя")
    apply_checkup_return(checkup, due)
    execute_dm(
        config,
        '<dm:request xsi:type="dm:DMUpdateRequest">'
        f"{_object_xml(checkup)}"
        "</dm:request>",
        timeout=timeout,
    )


def _new_execute_task_id(config: DokConfig, execute_task: ET.Element, *, timeout: float) -> str:
    target_id = xml_text(execute_task, "m:target/m:objectID/m:id")
    target_type = xml_text(execute_task, "m:target/m:objectID/m:type")
    old_id = xml_text(execute_task, "m:objectID/m:id")
    for row in open_tasks_for_target(config, target_id, target_type, timeout=timeout):
        step = " ".join(str(row.get("step") or "").lower().replace("ё", "е").split())
        task_id = str(row.get("id") or "")
        if task_id and task_id != old_id and "исполн" in step and not row.get("executed"):
            return task_id
    return ""


def return_task_for_rework(
    config: DokConfig,
    task_id: str,
    *,
    due: datetime,
    comment: str,
    timeout: float,
) -> dict[str, Any]:
    """Вернуть проверку в том же процессе: новый срок исполнителя и комментарий в истории."""
    task_id = str(task_id or "").strip()
    comment = " ".join(str(comment or "").split())
    if not task_id:
        raise ReworkError("Не указана задача")
    if not comment:
        raise ReworkError("Нужен комментарий, почему задача возвращена на доработку")
    source = _retrieve_task_node(config, task_id, timeout=timeout)
    process_id, process_type = business_process_ref(source)
    if not process_id:
        raise ReworkError("У задачи нет реквизита «БизнесПроцесс»")
    # Исполнитель уже закрыл свою задачу: возвращаем открытую «Проверку исполнения»,
    # а копию делаем с исполнительской задачи, чтобы она снова пришла исполнителю.
    copy_source = source
    close_id = task_id
    if _is_check(source):
        performer_task = _performer_task_node(config, source, timeout=timeout)
        if performer_task is not None:
            copy_source = performer_task
    elif _is_execute(source) and xml_text(source, "m:executed") == "true":
        close_id = _open_check_task_id(config, source, timeout=timeout)
        if not close_id:
            raise ReworkError(
                "Исполнитель уже закрыл задачу, но открытая «Проверка исполнения» не найдена"
            )
    _shift_process_due(config, copy_source, due=due, timeout=timeout)
    _save_checkup_return(config, close_id, due, timeout=timeout)
    try:
        closed = mark_task_executed(
            config,
            close_id,
            timeout=timeout,
            comment=comment,
            mark="ExecutedPositive",
        )
    except RuntimeError as exc:
        raise ReworkError(
            "Срок исполнителя сдвинут, но «Проверку исполнения» не удалось закрыть: "
            f"{exc}"
        ) from exc
    created_id = _new_execute_task_id(config, copy_source, timeout=timeout)
    logger.info(
        "Возврат на доработку: закрыта %s, создана %s в процессе %s (%s)",
        close_id,
        created_id,
        process_id,
        process_type,
    )
    return {
        "ok": True,
        "closed": True,
        "task_id": close_id,
        "new_task_id": created_id,
        "business_process_id": process_id,
        "business_process_type": process_type,
        "due": soap_datetime(due),
        "comment": comment,
        "closed_task": closed,
        "summary": "Задача возвращена на доработку в том же процессе. Новый срок и комментарий записаны в историю выполнения.",
    }
