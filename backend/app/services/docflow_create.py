"""Создание задачи в 1С:Документооборот: документ-основание → процесс → запуск."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.services.docflow_task_action import _session_credentials
from app.services.docflow_tasks import DocflowError
from app.tools.onec.dok_create import (
    fill_process,
    launch_business_process,
    list_internal_document_types,
    list_users,
    new_business_process,
    open_task_ids_by_step,
    parse_due,
    sample_performer,
    search_documents,
)
from app.tools.onec.dok_soap import find_user, load_config, xml_text

logger = logging.getLogger(__name__)

DOC_KINDS: list[dict[str, Any]] = [
    {
        "id": "protocol",
        "label": "Протокол",
        "hint": "Решения совещаний и заседаний",
        "dm_type": "DMInternalDocument",
        "pattern": r"протокол",
        "processes": ["performance", "acquaintance"],
    },
    {
        "id": "memo",
        "label": "Служебная записка",
        "hint": "Внутренние обращения и запросы",
        "dm_type": "DMInternalDocument",
        "pattern": r"служебн",
        "processes": ["performance", "acquaintance", "consideration"],
    },
    {
        "id": "order",
        "label": "Приказ",
        "hint": "Приказы по основной деятельности",
        "dm_type": "DMInternalDocument",
        "pattern": r"приказ",
        "processes": ["acquaintance", "performance"],
    },
    {
        "id": "directive",
        "label": "Распоряжение",
        "hint": "Распоряжения руководства",
        "dm_type": "DMInternalDocument",
        "pattern": r"распоряж",
        "processes": ["acquaintance", "performance"],
    },
    {
        "id": "contract",
        "label": "Договор",
        "hint": "Договоры, доп. соглашения, спецификации",
        "dm_type": "DMInternalDocument",
        "pattern": r"договор|соглашени|спецификац",
        "processes": ["performance"],
    },
    {
        "id": "request",
        "label": "Заявка",
        "hint": "Заявки и заказы",
        "dm_type": "DMInternalDocument",
        "pattern": r"заявк|заказ",
        "processes": ["performance", "consideration"],
    },
    {
        "id": "incoming",
        "label": "Входящий документ",
        "hint": "Письма, поступившие в компанию",
        "dm_type": "DMIncomingDocument",
        "author_field": "responsible",
        "processes": ["consideration", "performance"],
    },
    {
        "id": "outgoing",
        "label": "Исходящий документ",
        "hint": "Письма, отправленные из компании",
        "dm_type": "DMOutgoingDocument",
        "processes": ["performance"],
    },
]

PROCESSES: dict[str, dict[str, Any]] = {
    "performance": {
        "label": "Исполнение",
        "dm_type": "DMBusinessProcessPerformance",
        "hint": "Исполнители получат задачу «Исполнить», проверяющий — «Проверить исполнение».",
        "multiple": True,
        "verifier": True,
    },
    "acquaintance": {
        "label": "Ознакомление",
        "dm_type": "DMBusinessProcessAcquaintance",
        "hint": "Каждый участник получит задачу «Ознакомиться».",
        "multiple": True,
        "verifier": False,
    },
    "consideration": {
        "label": "Рассмотрение",
        "dm_type": "DMBusinessProcessConsideration",
        "hint": "Сотрудник получит «Рассмотреть», вы — «Обработать резолюцию».",
        "multiple": False,
        "verifier": False,
    },
}

_LOOKUP_TIMEOUT = 60.0
_SEARCH_TIMEOUT = 120.0


def _kind(kind_id: str) -> dict[str, Any]:
    for item in DOC_KINDS:
        if item["id"] == kind_id:
            return item
    raise DocflowError(f"Неизвестный вид документа-основания: {kind_id or '—'}")


def _process(kind: dict[str, Any], process_id: str) -> dict[str, Any]:
    if process_id not in PROCESSES:
        raise DocflowError(f"Неизвестный процесс: {process_id or '—'}")
    if process_id not in kind["processes"]:
        raise DocflowError(f"Для «{kind['label']}» процесс «{PROCESSES[process_id]['label']}» не используется")
    return PROCESSES[process_id]


def _config(args: dict[str, Any], actor_fio: str):
    user, password = _session_credentials(args)
    if not password:
        user = user or actor_fio.strip()
    if not user or not password:
        raise DocflowError("Нужны учётные данные сеанса 1С (ФИО и пароль)")
    return user, load_config(username=user, password=password, require_user=True)


def _resolve_user(config, fio: str) -> dict[str, str]:
    try:
        return find_user(config, fio)
    except ValueError as exc:
        raise DocflowError(str(exc)) from exc


def _types_for(kind: dict[str, Any], types: list[dict[str, str]]) -> list[dict[str, str]]:
    pattern = kind.get("pattern")
    if not pattern:
        return []
    return [item for item in types if re.search(pattern, item["name"], flags=re.I)]


def _catalog(config) -> dict[str, Any]:
    try:
        types = list_internal_document_types(config, timeout=_LOOKUP_TIMEOUT)
    except RuntimeError as exc:
        raise DocflowError(f"Виды документов ДО не получены: {exc}") from exc
    kinds = []
    for kind in DOC_KINDS:
        matched = _types_for(kind, types)
        if kind["dm_type"] == "DMInternalDocument" and not matched:
            continue
        kinds.append(
            {
                "id": kind["id"],
                "label": kind["label"],
                "hint": kind["hint"],
                "types": matched,
                "processes": kind["processes"],
            }
        )
    processes = [
        {"id": pid, "label": p["label"], "hint": p["hint"], "multiple": p["multiple"], "verifier": p["verifier"]}
        for pid, p in PROCESSES.items()
    ]
    return {"summary": "Каталог оснований ДО", "kinds": kinds, "processes": processes}


def _search(config, args: dict[str, Any], actor: str) -> dict[str, Any]:
    kind = _kind(str(args.get("kind") or ""))
    only_mine = args.get("only_mine") is not False
    author = _resolve_user(config, actor) if only_mine else None
    type_ids = [str(args.get("document_type_id") or "").strip()]
    if kind["dm_type"] == "DMInternalDocument" and not type_ids[0]:
        types = _types_for(kind, list_internal_document_types(config, timeout=_LOOKUP_TIMEOUT))
        type_ids = [item["id"] for item in types[:6]]
        if not type_ids:
            raise DocflowError(f"В ДО нет видов документов для «{kind['label']}»")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for type_id in type_ids:
        try:
            found = search_documents(
                config,
                kind["dm_type"],
                document_type_id=type_id,
                author=author,
                author_field=kind.get("author_field", "author"),
                query=str(args.get("query") or ""),
                limit=int(args.get("limit") or 50),
                timeout=_SEARCH_TIMEOUT,
            )
        except RuntimeError as exc:
            raise DocflowError(f"Поиск документов не выполнен: {exc}") from exc
        for row in found:
            if row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
    rows.sort(key=lambda row: row.get("reg_date") or "", reverse=True)
    return {"summary": f"Найдено документов: {len(rows)}", "documents": rows, "count": len(rows)}


def _target(args: dict[str, Any]) -> dict[str, str]:
    doc = args.get("document") if isinstance(args.get("document"), dict) else {}
    target = {"id": str(doc.get("id") or "").strip(), "type": str(doc.get("type") or "").strip()}
    if not target["id"] or not target["type"]:
        raise DocflowError("Не выбран документ-основание")
    return target


def _prepare(config, args: dict[str, Any]) -> dict[str, Any]:
    kind = _kind(str(args.get("kind") or ""))
    process = _process(kind, str(args.get("process") or ""))
    try:
        node = new_business_process(config, process["dm_type"], _target(args), timeout=_LOOKUP_TIMEOUT)
    except RuntimeError as exc:
        raise DocflowError(f"ДО не подготовил процесс: {exc}") from exc
    return {
        "summary": "Заготовка процесса получена",
        "name": xml_text(node, "m:name"),
        "description": xml_text(node, "m:description"),
        "author": xml_text(node, "m:author/m:name"),
        "target": xml_text(node, "m:target/m:name"),
    }


def _launch(config, args: dict[str, Any], actor: str) -> dict[str, Any]:
    if args.get("confirm") is not True:
        raise DocflowError("Запуск процесса требует подтверждения")
    kind = _kind(str(args.get("kind") or ""))
    process = _process(kind, str(args.get("process") or ""))
    target = _target(args)
    title = str(args.get("title") or "").strip()
    description = str(args.get("description") or "").strip()
    if not title:
        raise DocflowError("Укажите название задачи")
    try:
        due = parse_due(args.get("due"))
    except ValueError as exc:
        raise DocflowError(str(exc)) from exc
    priority = str(args.get("priority") or "").strip().lower()
    if priority and priority not in {"high", "normal", "low"}:
        raise DocflowError("Приоритет: high | normal | low")

    raw_performers = args.get("performers") if isinstance(args.get("performers"), list) else []
    performers: list[dict[str, Any]] = []
    for raw in raw_performers:
        if not isinstance(raw, dict) or not str(raw.get("fio") or "").strip():
            continue
        try:
            personal_due = parse_due(raw.get("due"))
        except ValueError as exc:
            raise DocflowError(str(exc)) from exc
        performers.append(
            {
                "user": _resolve_user(config, str(raw["fio"]).strip()),
                "due": personal_due,
                "note": str(raw.get("note") or "").strip(),
            }
        )
    if not performers:
        raise DocflowError("Укажите хотя бы одного исполнителя")
    if not process["multiple"] and len(performers) > 1:
        raise DocflowError(f"«{process['label']}» назначается одному сотруднику")

    verifier = None
    if process["verifier"]:
        verifier = _resolve_user(config, str(args.get("verifier") or actor).strip())

    template = None
    if process["dm_type"] == "DMBusinessProcessPerformance":
        ids = [str(item) for item in (args.get("sample_task_ids") or []) if str(item).strip()]
        ids += [item for item in open_task_ids_by_step(r"^исполнить$") if item not in ids]
        template = sample_performer(config, process["dm_type"], ids, timeout=_LOOKUP_TIMEOUT)
        logger.info("dok_create: образец участника %s", "найден" if template is not None else "не найден")

    try:
        node = new_business_process(config, process["dm_type"], target, timeout=_LOOKUP_TIMEOUT)
        fill_process(
            node,
            process["dm_type"],
            title=title,
            description=description,
            due=due,
            performers=performers,
            verifier=verifier,
            performer_template=template,
            priority=priority,
        )
        launched = launch_business_process(config, node, timeout=_LOOKUP_TIMEOUT)
    except ValueError as exc:
        raise DocflowError(str(exc)) from exc
    except RuntimeError as exc:
        raise DocflowError(f"ДО не запустил процесс: {exc}") from exc

    names = ", ".join(item["user"]["name"] for item in performers)
    return {
        "summary": f"Процесс «{process['label']}» запущен в документообороте. Задачи получат: {names}.",
        "process": launched,
        "performers": [item["user"]["name"] for item in performers],
    }


def handle_docflow_create(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
) -> dict[str, Any]:
    del actor_user_id
    action = str(args.get("action") or "").strip().lower()
    actor, config = _config(args, actor_fio)
    if action == "catalog":
        return _catalog(config)
    if action == "users":
        try:
            names = list_users(config, timeout=_SEARCH_TIMEOUT)
        except RuntimeError as exc:
            raise DocflowError(f"Пользователи ДО не получены: {exc}") from exc
        return {"summary": f"Пользователей ДО: {len(names)}", "users": names, "count": len(names)}
    if action == "search_documents":
        return _search(config, args, actor)
    if action == "prepare":
        return _prepare(config, args)
    if action == "launch":
        return _launch(config, args, actor)
    raise DocflowError("Укажите action: catalog | users | search_documents | prepare | launch")


def stub_docflow_create(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    return {
        "summary": "stub: docflow_create",
        "action": str(args.get("action") or ""),
        "ok": False,
        "message": "Настройте DOK_HTTP_* на backend для создания задач в документообороте",
    }
