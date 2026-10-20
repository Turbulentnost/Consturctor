"""Задачи 1С:Документооборот по поручениям АСТ00.

Поручение ERP отражено в ДО внутренним документом с тем же GUID. Задачи ДО ссылаются
только на поручение целиком: ни номера, ни ссылки на строку-мероприятие в них нет,
поэтому задачи показываются по поручению, без раскладки по пунктам.

Задача поручения — цепочка одного бизнес-процесса «Исполнение»: задачи исполнителя,
проверки автора, возвраты на доработку и переносы срока. Номер задачи ДО — номер
процесса плюс пять цифр шага, по нему задачи собираются в цепочку. task_id нужен,
чтобы закрыть задачу или вернуть её на доработку (onec.docflow_task_action /
onec.docflow_rework).
"""

from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

_TASK_DATE_RE = re.compile(r"от (\d{2})\.(\d{2})\.(\d{4}) (\d{1,2}):(\d{2}):(\d{2})")
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_REPORT_CHARS = 600
_TEXT_CHARS = 300
_STEP_DIGITS = 5
ACCEPTED = "принято проверяющим"
_MAX_WORKERS = 6


def _fold(value: Any) -> str:
    return " ".join(str(value or "").casefold().replace("ё", "е").split())


def task_kind(row: dict[str, Any]) -> str:
    text = _fold(f"{row.get('step') or ''} {row.get('name') or ''}")
    if any(tip in text for tip in ("ознаком", "перенос срока", "согласова", "рассмотреть вопрос")):
        return "other"
    if any(tip in text for tip in ("провер", "контрол", "утверд", "подтверд", "принят")):
        return "check"
    if "исполн" in text or "отправ" in text:
        return "execute"
    return "other"


def _clip(value: Any, size: int = _REPORT_CHARS) -> str:
    text = str(value or "").strip()
    return text[:size].rstrip() + "…" if len(text) > size else text


def chain_key(row: dict[str, Any]) -> str:
    """Номер процесса ДО: номер задачи без пяти цифр шага. Без номера задача — сама себе цепочка."""
    number = str(row.get("number") or "").strip()
    if len(number) > _STEP_DIGITS and number[-_STEP_DIGITS:].isdigit():
        return number[:-_STEP_DIGITS]
    return f"task:{row.get('id') or id(row)}"


def _task_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": str(row.get("id") or ""),
        "kind": task_kind(row),
        "step": str(row.get("step") or ""),
        "name": str(row.get("name") or "")[:160],
        "performer": str(row.get("performer") or ""),
        "author": str(row.get("author") or ""),
        "begin": str(row.get("begin") or "")[:19],
        "end": str(row.get("end") or "")[:19],
        "due": str(row.get("due") or "")[:10],
        "executed": bool(row.get("executed")),
        "mark": str(row.get("execution_mark") or ""),
        "text": _clip(row.get("description"), _TEXT_CHARS),
        "report": _clip(row.get("comment")),
    }


def _named_task_at(name: str) -> str:
    """Начало задачи, о которой задача переноса срока: последняя дата «от ДД.ММ.ГГГГ Ч:ММ:СС» в имени."""
    found = _TASK_DATE_RE.findall(name)
    if not found:
        return ""
    day, month, year, hour, minute, second = found[-1]
    return f"{year}-{month}-{day}T{int(hour):02d}:{minute}:{second}"


def _unique_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Одна задача из двух выборок ДО (все и открытые): поля дополняют друг друга."""
    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        merged = unique.setdefault(str(row.get("id") or id(row)), {})
        for field, value in row.items():
            if value not in (None, "") and merged.get(field) in (None, ""):
                merged[field] = value
    return sorted(unique.values(), key=lambda r: (str(r.get("begin") or ""), str(r.get("number") or "")))


def task_state(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Где сейчас задача по маршруту ДО. Отметка проверки ExecutedNegative — возврат, не приёмка."""
    executes = [task for task in tasks if task["kind"] == "execute"]
    checks = [task for task in tasks if task["kind"] == "check"]
    last_exec = executes[-1] if executes else None
    last_check = checks[-1] if checks else None
    open_check = next((task for task in reversed(checks) if not task["executed"]), None)
    open_exec = next((task for task in reversed(executes) if not task["executed"]), None)
    checked_last = bool(
        last_check and last_check["executed"] and (not last_exec or last_check["begin"] >= last_exec["begin"])
    )
    if not tasks:
        label = "задачи в Документообороте нет"
    elif open_check:
        label = "исполнитель отчитался, ждёт проверки"
    elif open_exec:
        label = "у исполнителя, не выполнено"
    elif checked_last and last_check["mark"] == "ExecutedNegative":
        label = "возвращено на доработку"
    elif checked_last:
        label = ACCEPTED
    elif last_exec and last_exec["executed"] and last_exec["mark"] == "ExecutedNegative":
        label = "исполнитель отметил: не выполнено"
    elif last_exec and last_exec["executed"]:
        label = "исполнитель отметил выполнение"
    else:
        label = "статус не определён"
    accepted = label == ACCEPTED
    return {
        "label": label,
        "returns": max(0, len(executes) - 1, sum(1 for task in checks if task["mark"] == "ExecutedNegative")),
        "executor_report": next(
            (task["report"] for task in reversed(executes) if task["executed"] and task["report"]), ""
        ),
        "accepted_at": last_check["begin"][:10] if accepted else "",
        "accepted_by": last_check["performer"] if accepted else "",
        "open_check_task_id": open_check["task_id"] if open_check else "",
        "open_check_step": open_check["step"] if open_check else "",
        "open_check_name": open_check["name"] if open_check else "",
        "open_check_performer": open_check["performer"] if open_check else "",
        "open_execute_task_id": open_exec["task_id"] if open_exec else "",
    }


def _history_view(task: dict[str, Any]) -> dict[str, Any]:
    keep = ("task_id", "kind", "step", "performer", "begin", "end", "due", "executed", "mark", "report")
    return {field: task[field] for field in keep}


def build_tasks(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Задачи поручения (цепочки исполнения по порядку отправки) и прочие задачи вне цепочек."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in _unique_rows(rows):
        view = _task_view(row)
        groups.setdefault(chain_key(row), []).append(view)
    chains = {key: tasks for key, tasks in groups.items() if any(task["kind"] == "execute" for task in tasks)}
    by_start = {task["begin"]: key for key, tasks in chains.items() for task in tasks if task["kind"] == "execute"}
    other: list[dict[str, Any]] = []
    for key, tasks in groups.items():
        if key in chains:
            continue
        for task in tasks:
            owner = by_start.get(_named_task_at(task["name"])) if task["kind"] == "other" else None
            if owner:
                chains[owner].append(task)
            else:
                other.append(task)
    result: list[dict[str, Any]] = []
    for key, tasks in chains.items():
        tasks.sort(key=lambda task: task["begin"])
        executes = [task for task in tasks if task["kind"] == "execute"]
        result.append(
            {
                "chain": key,
                "performer": executes[0]["performer"],
                "author": executes[0]["author"],
                "text": next((task["text"] for task in executes if task["text"]), ""),
                "begin": tasks[0]["begin"][:10],
                "due": executes[-1]["due"],
                **task_state(tasks),
                "history": [_history_view(task) for task in tasks],
                "files": [],
            }
        )
    result.sort(key=lambda chain: chain["begin"])
    return result, [_history_view(task) | {"name": task["name"]} for task in other]


def _executors_without_tasks(lines: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> list[str]:
    from app.tools.onec.dok_soap import person_names_match

    missing: list[str] = []
    for line in lines:
        executor = str(line.get("executor") or "").strip()
        if not executor or executor in missing:
            continue
        if not any(person_names_match(executor, task["performer"]) for task in tasks):
            missing.append(executor)
    return missing


def _sending_for(task: dict[str, Any], created: str) -> tuple[int, str, dict[str, Any]] | None:
    """Отправка исполнителю для файла: 2 — загружен во время неё, 1 — после неё, 0 — до первой."""
    executes = [step for step in task["history"] if step["kind"] == "execute"]
    started = [step for step in executes if step["begin"] and step["begin"] <= created]
    within = [step for step in started if not step["end"] or created <= step["end"]]
    for rank, steps in ((2, within), (1, started), (0, executes)):
        if steps:
            return rank, steps[-1]["begin"], steps[-1]
    return None


def attach_files(tasks: list[dict[str, Any]], files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Раскладывает файлы вкладки «Файлы» поручения ERP по задачам ДО.

    Ссылки файла на задачу в 1С нет. Загрузивший файл (Изменил) — исполнитель задачи,
    дата загрузки выбирает отправку. Остальные файлы — файлы самого поручения.
    """
    from app.tools.onec.dok_soap import person_names_match

    unmatched: list[dict[str, Any]] = []
    for file in files:
        who = str(file.get("uploaded_by") or "").strip()
        created = str(file.get("created") or "")[:19]
        mine = [task for task in tasks if who and person_names_match(who, task["performer"])]
        picks = [(task, _sending_for(task, created)) for task in mine]
        picks = [(task, pick) for task, pick in picks if pick]
        if not picks:
            unmatched.append(file)
            continue
        task, (_, _, step) = max(picks, key=lambda pick: pick[1][:2])
        task["files"].append(file | {"task_id": step["task_id"]})
    return unmatched


def link_tasks(item: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Задачи ДО поручения без привязки к пунктам: в ДО у задачи нет ссылки на строку поручения."""
    lines = item.get("lines") if isinstance(item.get("lines"), list) else []
    tasks, other = build_tasks(rows)
    files = item.get("files") if isinstance(item.get("files"), list) else []
    item["docflow_assignment_files"] = attach_files(tasks, files)
    open_tasks = sum(1 for task in tasks for step in task["history"] if not step["executed"])
    open_tasks += sum(1 for task in other if not task["executed"])
    accepted = sum(1 for task in tasks if task["label"] == ACCEPTED)
    item["docflow_tasks"] = tasks
    item["docflow_other_tasks"] = other
    item["docflow_summary"] = {
        "total": len(tasks),
        "accepted": accepted,
        "open_tasks": open_tasks,
        "all_accepted": bool(tasks) and accepted == len(tasks) and not open_tasks,
        "executors_without_tasks": _executors_without_tasks(lines, tasks),
    }


def _target_rows(config: Any, ref: str) -> list[dict[str, Any]]:
    """withExecuted=true в этой базе отдаёт только исполненные задачи: открытые читаем отдельно."""
    from app.services.docflow_protocols import _DO_TARGET_TYPE, _DO_TIMEOUT_SEC, _do_request
    from app.tools.onec.dok_soap import open_tasks_for_target

    rows = _do_request(config, ref)
    try:
        rows += open_tasks_for_target(config, ref, _DO_TARGET_TYPE, timeout=_DO_TIMEOUT_SEC)
    except (RuntimeError, ValueError, OSError, ET.ParseError) as exc:
        logger.warning("open docflow tasks for %s failed: %s", ref, str(exc)[:200])
    return rows


def _rows_for(config: Any, refs: list[str]) -> dict[str, list[dict[str, Any]]]:
    with ThreadPoolExecutor(max_workers=min(_MAX_WORKERS, len(refs))) as pool:
        futures = {ref: pool.submit(_target_rows, config, ref) for ref in refs}
        return {ref: future.result() for ref, future in futures.items()}


def _service_login() -> tuple[str, str]:
    """Служебная учётка ДО (DOK_HTTP_*): серверный запуск идёт без пароля пользователя."""
    from app.config import settings

    user = (os.environ.get("DOK_HTTP_USER") or settings.dok_http_user or "").strip()
    password = (os.environ.get("DOK_HTTP_PASSWORD") or settings.dok_http_password or "").strip()
    return (user, password) if user and password else ("", "")


def _session_rows(args: dict[str, Any], refs: list[str]) -> tuple[dict[str, list[dict[str, Any]]], str]:
    from app.tools.onec.docflow_inbox_fetch import _is_soap_http_auth_error, _soap_login_attempts
    from app.tools.onec.dok_soap import load_config

    error = "нет пароля 1С сеанса"
    attempts = list(_soap_login_attempts(args)) if str(args.get("password") or "").strip() else []
    service = _service_login()
    if service[0] and service not in attempts:
        attempts.append(service)
    for username, password in attempts:
        try:
            return _rows_for(load_config(username=username, password=password), refs), ""
        except (RuntimeError, ValueError, OSError, ET.ParseError) as exc:
            error = str(exc)
            if _is_soap_http_auth_error(error):
                continue
            logger.warning("assignment docflow tasks failed: %s", error[:300])
            break
    return {}, error


def attach_docflow_tasks(items: list[dict[str, Any]], args: dict[str, Any]) -> str:
    """Добавляет задачи ДО к мероприятиям. Возвращает пометку, если видны только открытые задачи."""
    refs = [
        str(item.get("ref_key") or "")
        for item in items
        if _GUID_RE.match(str(item.get("ref_key") or ""))
    ]
    refs = list(dict.fromkeys(refs))
    if not refs:
        return ""
    session = {
        "fio": str(args.get("docflow_login") or "").strip(),
        "password": str(args.get("docflow_password") or ""),
    }
    by_ref, error = _session_rows(session, refs)
    note = ""
    if error:
        from app.services.docflow_protocols import _dump_open_rows

        by_ref = _dump_open_rows(refs)
        note = (
            f"Документооборот под пользователем недоступен ({error[:160]}): "
            "показаны только открытые задачи из последней выгрузки, выполненных задач здесь нет"
        )
    for item in items:
        link_tasks(item, by_ref.get(str(item.get("ref_key") or ""), []))
    return note
