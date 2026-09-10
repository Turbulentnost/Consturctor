"""Porucheniya journal in 1C ERP via OData (Document_TD_Porucheniya)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

ASSIGNMENT_ENTITY = "Document_ТД_Поручения"
ASSIGNMENT_LINES_ENTITY = "Document_ТД_Поручения_Поручения"
ASSIGNMENT_FILES_ENTITY = "Catalog_ТД_ПорученияПрисоединенныеФайлы"
PROTOCOL_ENTITY = "Document_ТД_Протокол"
USER_ENTITY = "Catalog_Пользователи"
TASK_ENTITY = "Task_ЗадачаИсполнителя"
NUMBER_PREFIX = "АСТ"

OPEN_STATUSES = {
    "создано",
    "вработе",
    "в работе",
    "напроверке",
    "на проверке",
    "выполнено (ожидает приемки)",
}
CLOSED_STATUSES = {
    "принято",
    "исполнено",
    "закрыто",
    "выполнено",
    "принято и закрыто",
}

_GUID_EMPTY = "00000000-0000-0000-0000-000000000000"


class AssignmentError(RuntimeError):
    pass


def _odata_get(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _fetch_odata_list

    return _fetch_odata_list(args)


def _odata_post(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_post

    return _odata_post(args)


def _odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_tools import _odata_patch

    return _odata_patch(args)


def _empty_guid(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text.startswith(_GUID_EMPTY)


def _odata_datetime(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def _parse_day(raw: str, *, end: bool = False) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text[:19], fmt)
            if end and parsed.hour == 0 and parsed.minute == 0 and len(text) <= 10:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            return parsed
        except ValueError:
            continue
    raise AssignmentError(f"Nepopyatnaya data: {text}")


def _status_open(status: str) -> bool:
    key = "".join(str(status or "").casefold().split())
    if not key:
        return True
    if key in {"".join(item.split()) for item in CLOSED_STATUSES}:
        return False
    if key in {"".join(item.split()) for item in OPEN_STATUSES}:
        return True
    return key not in {"".join(item.split()) for item in CLOSED_STATUSES}


def _overdue(due_raw: Any, *, open_item: bool) -> bool:
    if not open_item or not due_raw:
        return False
    text = str(due_raw)
    if text.startswith("0001-01-01"):
        return False
    try:
        due = datetime.fromisoformat(text[:19])
    except ValueError:
        return False
    return due.date() < datetime.now().date()


def _name_of(row: dict[str, Any], key: str) -> str:
    for item in (f"{key}_Name", key):
        value = row.get(item)
        text = str(value or "").strip()
        if text and not _empty_guid(text) and "@" not in item:
            return text
    return ""


def pick_user_row(rows: list[dict[str, Any]], query: str) -> dict[str, Any] | None:
    needle = " ".join(str(query or "").split()).casefold()
    if not needle or not rows:
        return None
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        name = str(row.get("Description") or row.get("Subject") or "").strip()
        low = name.casefold()
        if low == needle:
            scored.append((0, row))
        elif low.startswith(needle) or needle.startswith(low):
            scored.append((1, row))
        elif needle in low:
            scored.append((2 + len(low), row))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], len(str(item[1].get("Description") or ""))))
    return scored[0][1]


def resolve_user(query: str) -> dict[str, str]:
    text = " ".join(str(query or "").split())
    if not text:
        raise AssignmentError("Nuzhno FIO zakazchika ili ispolnitelya")
    if len(text) == 36 and text.count("-") == 4:
        return {"ref_key": text, "fio": text}
    result = _odata_get(
        {
            "entity": USER_ENTITY,
            "top": 20,
            "filter": f"substringof('{text.replace(chr(39), chr(39)+chr(39))}', Description)",
        }
    )
    rows = [row for row in (result.get("value") or []) if isinstance(row, dict)]
    chosen = pick_user_row(rows, text)
    if chosen is None:
        raise AssignmentError(f"Polzovatel 1C ne nayden: {text}")
    return {
        "ref_key": str(chosen.get("Ref_Key") or ""),
        "fio": str(chosen.get("Description") or chosen.get("Subject") or text),
    }


def build_assignment_filter(
    *,
    customer_key: str = "",
    number: str = "",
    query: str = "",
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    only_open: bool = False,
    changed_since: datetime | None = None,
    number_prefix: str = NUMBER_PREFIX,
) -> str:
    parts: list[str] = ["DeletionMark eq false"]
    if number_prefix:
        safe = number_prefix.replace("'", "''")
        parts.append(f"startswith(Number,'{safe}')")
    if number:
        parts.append(f"Number eq '{number.replace(chr(39), chr(39)+chr(39))}'")
    if customer_key:
        parts.append(f"Руководитель_Key eq guid'{customer_key}'")
    if query:
        safe = query.replace("'", "''")
        parts.append(f"substringof('{safe}', ОЧем)")
    if date_from is not None:
        parts.append(f"Date ge datetime'{_odata_datetime(date_from)}'")
    if date_to is not None:
        parts.append(f"Date le datetime'{_odata_datetime(date_to)}'")
    if only_open and changed_since is None:
        opened = " or ".join(f"Статус eq '{item}'" for item in ("Создано", "ВРаботе"))
        parts.append(f"({opened})")
    elif changed_since is not None:
        opened = " or ".join(f"Статус eq '{item}'" for item in ("Создано", "ВРаботе"))
        parts.append(
            f"(({opened}) or Date ge datetime'{_odata_datetime(changed_since)}')"
        )
    return " and ".join(parts)


def _normalize_line(row: dict[str, Any]) -> dict[str, Any]:
    due = row.get("СрокИсполнения")
    executor = _name_of(row, "ОтветственноеЛицо")
    open_item = True
    return {
        "line": int(str(row.get("LineNumber") or "0") or 0),
        "text": str(row.get("Мероприятие") or "").strip(),
        "due": str(due or ""),
        "executor": executor,
        "executor_key": str(row.get("ОтветственноеЛицо_Key") or ""),
        "priority": str(row.get("Приоритет") or "").strip(),
        "overdue": _overdue(due, open_item=open_item),
    }


def _normalize_file(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(row.get("Description") or row.get("Subject") or "").strip(),
        "extension": str(row.get("Расширение") or "").strip(),
        "size": row.get("Размер") or 0,
        "path": str(row.get("ПутьКФайлу") or "").strip(),
        "created": str(row.get("ДатаСоздания") or ""),
        "ref_key": str(row.get("Ref_Key") or ""),
        "owner_key": str(row.get("ВладелецФайла_Key") or ""),
    }


def _normalize_assignment(row: dict[str, Any], *, files: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    status = str(row.get("Статус") or "").strip()
    due = row.get("СрокПолногоУстраненияНарушений")
    lines_raw = row.get("Поручения")
    if not isinstance(lines_raw, list):
        parts = row.get("tabular_parts")
        if isinstance(parts, dict):
            lines_raw = parts.get(ASSIGNMENT_LINES_ENTITY)
    lines = [_normalize_line(item) for item in lines_raw or [] if isinstance(item, dict)]
    opened = _status_open(status)
    return {
        "number": str(row.get("Number") or ""),
        "ref_key": str(row.get("Ref_Key") or ""),
        "date": str(row.get("Date") or ""),
        "posted": bool(row.get("Posted")),
        "status": status,
        "open": opened,
        "topic": str(row.get("ОЧем") or row.get("Subject") or "").strip(),
        "basis": str(row.get("Основание") or "").strip(),
        "customer": _name_of(row, "Руководитель"),
        "customer_key": str(row.get("Руководитель_Key") or ""),
        "secretary": _name_of(row, "СекретарьРК"),
        "reporter": _name_of(row, "КтоДоложитОЗавершенииМероприятий"),
        "organization": _name_of(row, "Организация"),
        "due": str(due or ""),
        "weekly_report_date": str(row.get("ДатаЕженедельногоОтчетаОВыполненииМероприятий") or ""),
        "final_report_date": str(row.get("ДатаИтоговогоДоклада") or ""),
        "overdue": _overdue(due, open_item=opened),
        "lines": lines,
        "files": files or [],
    }


def _looks_like_guid(value: str) -> bool:
    text = str(value or "").strip()
    return len(text) == 36 and text.count("-") == 4


def _fetch_lines_map(ref_keys: list[str]) -> dict[str, list[dict[str, Any]]]:
    keys = [key for key in dict.fromkeys(ref_keys) if _looks_like_guid(key)]
    out: dict[str, list[dict[str, Any]]] = {}
    for index in range(0, len(keys), 15):
        chunk = keys[index : index + 15]
        filt = " or ".join(f"Ref_Key eq guid'{key}'" for key in chunk)
        try:
            result = _odata_get({"entity": ASSIGNMENT_LINES_ENTITY, "top": 200, "filter": filt})
        except Exception:  # noqa: BLE001
            continue
        for row in result.get("value") or []:
            if not isinstance(row, dict):
                continue
            out.setdefault(str(row.get("Ref_Key") or ""), []).append(row)
    return out


def _attach_missing_lines(rows: list[dict[str, Any]]) -> None:
    missing = []
    for row in rows:
        lines = row.get("Поручения")
        if isinstance(lines, list) and lines:
            continue
        parts = row.get("tabular_parts")
        if isinstance(parts, dict) and parts.get(ASSIGNMENT_LINES_ENTITY):
            row["Поручения"] = parts.get(ASSIGNMENT_LINES_ENTITY)
            continue
        key = str(row.get("Ref_Key") or "")
        if _looks_like_guid(key):
            missing.append(key)
    if not missing:
        return
    found = _fetch_lines_map(missing)
    for row in rows:
        key = str(row.get("Ref_Key") or "")
        if key in found:
            row["Поручения"] = found[key]


def _user_names_by_keys(keys: list[str]) -> dict[str, str]:
    unique = [key for key in dict.fromkeys(keys) if _looks_like_guid(key)]
    names: dict[str, str] = {}
    for index in range(0, len(unique), 10):
        chunk = unique[index : index + 10]
        filt = " or ".join(f"Ref_Key eq guid'{key}'" for key in chunk)
        try:
            result = _odata_get({"entity": USER_ENTITY, "top": 20, "filter": filt})
        except Exception:  # noqa: BLE001
            continue
        for row in result.get("value") or []:
            if not isinstance(row, dict):
                continue
            key = str(row.get("Ref_Key") or "")
            name = str(row.get("Description") or row.get("Subject") or "").strip()
            if key and name:
                names[key] = name
    return names


def _enrich_assignment_names(
    items: list[dict[str, Any]],
    *,
    customer: str = "",
    customer_key: str = "",
) -> None:
    executor_keys: list[str] = []
    for item in items:
        if customer and not item.get("customer"):
            item["customer"] = customer
        if customer_key and not item.get("customer_key"):
            item["customer_key"] = customer_key
        for line in item.get("lines") or []:
            if isinstance(line, dict) and not line.get("executor"):
                executor_keys.append(str(line.get("executor_key") or ""))
    if not executor_keys:
        return
    names = _user_names_by_keys(executor_keys)
    for item in items:
        for line in item.get("lines") or []:
            if not isinstance(line, dict) or line.get("executor"):
                continue
            line["executor"] = names.get(str(line.get("executor_key") or ""), "")


def _fetch_files(ref_key: str) -> list[dict[str, Any]]:
    if _empty_guid(ref_key):
        return []
    result = _odata_get(
        {
            "entity": ASSIGNMENT_FILES_ENTITY,
            "top": 50,
            "filter": f"ВладелецФайла_Key eq guid'{ref_key}'",
        }
    )
    return [_normalize_file(row) for row in (result.get("value") or []) if isinstance(row, dict)]


def _list_assignments(args: dict[str, Any]) -> dict[str, Any]:
    customer = str(args.get("customer") or args.get("zakazchik") or args.get("fio") or "").strip()
    customer_key = str(args.get("customer_key") or args.get("Руководитель_Key") or "").strip()
    resolved = {}
    if customer and not customer_key:
        resolved = resolve_user(customer)
        customer_key = resolved["ref_key"]
        customer = resolved["fio"]
    number = str(args.get("number") or "").strip()
    query = str(args.get("query") or args.get("topic") or "").strip()
    date_from = _parse_day(str(args.get("date_from") or ""))
    date_to = _parse_day(str(args.get("date_to") or ""), end=True)
    only_open = args.get("only_open")
    include_day = args.get("include_last_day")
    changed_since = None
    open_only = False
    if date_from is None and date_to is None:
        if only_open is True and include_day is False:
            open_only = True
        elif only_open is True and include_day is not True:
            open_only = True
        else:
            changed_since = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    elif only_open is True:
        open_only = True
    top = max(1, min(int(args.get("limit") or args.get("top") or 40), 100))
    include_files = bool(args.get("include_files"))
    filt = build_assignment_filter(
        customer_key=customer_key,
        number=number,
        query=query,
        date_from=date_from,
        date_to=date_to,
        only_open=open_only,
        changed_since=changed_since,
    )
    result = _odata_get({"entity": ASSIGNMENT_ENTITY, "top": top, "filter": filt})
    raw_rows = [row for row in (result.get("value") or []) if isinstance(row, dict)]
    _attach_missing_lines(raw_rows)
    items = []
    for row in raw_rows:
        files = _fetch_files(str(row.get("Ref_Key") or "")) if include_files else []
        items.append(_normalize_assignment(row, files=files))
    _enrich_assignment_names(items, customer=customer, customer_key=customer_key)
    summary = f"Porucheniya 1C: {len(items)}"
    if customer:
        summary += f" (zakazchik {customer})"
    return {
        "summary": summary,
        "entity": ASSIGNMENT_ENTITY,
        "number_series": "АСТ00",
        "customer": customer,
        "customer_key": customer_key,
        "filter": filt,
        "count": len(items),
        "assignments": items,
        "source": result.get("source") or "odata",
    }


def _get_assignment(args: dict[str, Any]) -> dict[str, Any]:
    number = str(args.get("number") or "").strip()
    ref_key = str(args.get("ref_key") or args.get("Ref_Key") or "").strip()
    if not number and not ref_key:
        raise AssignmentError("Nuzhen number (AST00-...) ili ref_key")
    call: dict[str, Any] = {"entity": ASSIGNMENT_ENTITY, "top": 5}
    if ref_key:
        call["ref_key"] = ref_key
    else:
        call["number"] = number
    result = _odata_get(call)
    rows = [row for row in (result.get("value") or []) if isinstance(row, dict)]
    if not rows:
        raise AssignmentError(f"Poruchenie ne naydeno: {number or ref_key}")
    row = rows[0]
    _attach_missing_lines([row])
    files = _fetch_files(str(row.get("Ref_Key") or ""))
    item = _normalize_assignment(row, files=files)
    _enrich_assignment_names([item])
    return {
        "summary": f"Kartochka {item['number']}: {item['status']}, strok {len(item['lines'])}, faylov {len(files)}",
        "entity": ASSIGNMENT_ENTITY,
        "assignment": item,
        "count": 1,
        "source": result.get("source") or "odata",
    }


def _list_files(args: dict[str, Any]) -> dict[str, Any]:
    ref_key = str(args.get("ref_key") or args.get("Ref_Key") or "").strip()
    number = str(args.get("number") or "").strip()
    if not ref_key and number:
        card = _get_assignment({"number": number})
        item = card.get("assignment") or {}
        return {
            "summary": f"Fayly {item.get('number')}: {len(item.get('files') or [])}",
            "number": item.get("number"),
            "ref_key": item.get("ref_key"),
            "count": len(item.get("files") or []),
            "files": item.get("files") or [],
            "source": "odata",
        }
    files = _fetch_files(ref_key)
    return {
        "summary": f"Fayly porucheniya: {len(files)}",
        "ref_key": ref_key,
        "count": len(files),
        "files": files,
        "source": "odata",
    }


def _download_assignment_files(args: dict[str, Any]) -> dict[str, Any]:
    from app.services.onec_artifacts import handle_download_artifact

    file_id = str(args.get("file_id") or args.get("file_ref_key") or "").strip()
    if file_id:
        return handle_download_artifact(
            {"file_id": file_id, "entity": str(args.get("entity") or ASSIGNMENT_FILES_ENTITY)}
        )
    listed = _list_files(args)
    items = [row for row in (listed.get("files") or []) if isinstance(row, dict)]
    if not items:
        return {
            "summary": "Net faylov dlya skachivaniya",
            "count": 0,
            "files": [],
            "source": listed.get("source") or "odata",
        }
    downloaded: list[dict[str, Any]] = []
    for item in items:
        fid = str(item.get("ref_key") or "").strip()
        if not fid:
            continue
        downloaded.append(
            handle_download_artifact(
                {"file_id": fid, "entity": ASSIGNMENT_FILES_ENTITY}
            )
        )
    return {
        "summary": f"Skachano faylov: {len(downloaded)}",
        "number": listed.get("number"),
        "ref_key": listed.get("ref_key"),
        "count": len(downloaded),
        "files": downloaded,
        "source": "odata",
    }


def _list_tasks(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    performer = str(args.get("performer") or args.get("fio") or "").strip()
    only_open = args.get("only_open")
    if only_open is None:
        only_open = True
    top = max(1, min(int(args.get("limit") or 20), 100))
    parts = ["DeletionMark eq false"]
    if query:
        safe = query.replace("'", "''")
        parts.append(f"(substringof('{safe}', Description) or substringof('{safe}', ПредметСтрокой))")
    if only_open:
        parts.append("Executed eq false")
    if performer:
        user = resolve_user(performer)
        parts.append(f"Исполнитель eq guid'{user['ref_key']}'")
        performer = user["fio"]
    filt = " and ".join(parts)
    try:
        result = _odata_get({"entity": TASK_ENTITY, "top": top, "filter": filt})
        rows = [row for row in (result.get("value") or []) if isinstance(row, dict)]
        source = result.get("source") or "odata"
    except Exception as exc:  # noqa: BLE001
        return {
            "summary": f"Zadachi 1C po filtru ne prochitalis: {exc}",
            "query": query,
            "count": 0,
            "tasks": [],
            "hint": (
                "Zhurnal porucheniy - action=list (Document_TD_Porucheniya, AST00). "
                "V 1C net zadachi 'Proverit poruchenie': agent sam chitaet zhurnal. "
                "Ne ischi ee cherez onec.erp_tasks_current."
            ),
            "source": "error",
        }
    tasks = []
    for row in rows:
        tasks.append(
            {
                "number": str(row.get("Number") or ""),
                "title": str(row.get("Description") or row.get("Subject") or "").strip(),
                "subject": str(row.get("ПредметСтрокой") or "").strip(),
                "done": bool(row.get("Executed")),
                "due": str(row.get("СрокИсполнения") or ""),
                "author": _name_of(row, "Автор") or str(row.get("Автор") or ""),
                "performer": _name_of(row, "Исполнитель") or str(row.get("Исполнитель") or ""),
                "comment": str(row.get("РезультатВыполнения") or "").strip(),
                "ref_key": str(row.get("Ref_Key") or ""),
            }
        )
    return {
        "summary": f"Zadachi 1C: {len(tasks)}" + (f" ({performer})" if performer else ""),
        "query": query,
        "filter": filt,
        "count": len(tasks),
        "tasks": tasks,
        "hint": (
            "Esli nuzhen zhurnal porucheniy AST00 - action=list. "
            "Zadachi 'Proverit poruchenie' v 1C net, agent sam chitaet zhurnal."
        ),
        "source": source,
    }


def _list_protocols(args: dict[str, Any]) -> dict[str, Any]:
    date_from = _parse_day(str(args.get("date_from") or "")) or (
        datetime.now() - timedelta(days=14)
    )
    date_to = _parse_day(str(args.get("date_to") or ""), end=True)
    number = str(args.get("number") or "").strip()
    top = max(1, min(int(args.get("limit") or 10), 50))
    parts = [
        "DeletionMark eq false",
        f"Date ge datetime'{_odata_datetime(date_from)}'",
    ]
    if date_to is not None:
        parts.append(f"Date le datetime'{_odata_datetime(date_to)}'")
    if number:
        parts.append(f"Number eq '{number.replace(chr(39), chr(39)+chr(39))}'")
    result = _odata_get({"entity": PROTOCOL_ENTITY, "top": top, "filter": " and ".join(parts)})
    items = []
    for row in result.get("value") or []:
        if not isinstance(row, dict):
            continue
        decisions = row.get("Решения")
        if not isinstance(decisions, list):
            parts_map = row.get("tabular_parts")
            if isinstance(parts_map, dict):
                decisions = parts_map.get("Document_ТД_Протокол_Решения")
        items.append(
            {
                "number": str(row.get("Number") or ""),
                "ref_key": str(row.get("Ref_Key") or ""),
                "date": str(row.get("Date") or ""),
                "status": str(row.get("Статус") or ""),
                "people": str(row.get("КраткийСоставДокумента") or "").strip(),
                "comment": str(row.get("Комментарий") or "").strip(),
                "decisions": decisions or [],
            }
        )
    return {
        "summary": f"Protokoly 1C: {len(items)}",
        "entity": PROTOCOL_ENTITY,
        "count": len(items),
        "protocols": items,
        "source": result.get("source") or "odata",
    }


def handle_assignments(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    _ = actor_user_id
    action = str(args.get("action") or "list").strip().casefold()
    payload = dict(args)
    if action == "list" and not payload.get("customer") and actor_fio:
        # Customer is the leader, not the session user. Do not substitute.
        pass
    handlers = {
        "list": _list_assignments,
        "get": _get_assignment,
        "files": _list_files,
        "download": _download_assignment_files,
        "tasks": _list_tasks,
        "protocols": _list_protocols,
        "protocol": _list_protocols,
    }
    handler = handlers.get(action)
    if handler is None:
        raise AssignmentError(
            "action: list | get | files | download | tasks | protocols. "
            "Zapis - onec.erp_assignments_write."
        )
    return handler(payload)


def build_create_body(args: dict[str, Any]) -> dict[str, Any]:
    topic = str(args.get("topic") or args.get("ОЧем") or "").strip()
    if not topic:
        raise AssignmentError("Dlya create nuzhen topic / ОЧем")
    customer = str(args.get("customer") or "").strip()
    customer_key = str(args.get("customer_key") or "").strip()
    if customer and not customer_key:
        customer_key = resolve_user(customer)["ref_key"]
    if not customer_key:
        raise AssignmentError("Dlya create nuzhen customer (FIO zakazchika)")
    due = str(args.get("due") or args.get("СрокПолногоУстраненияНарушений") or "").strip()
    lines_in = args.get("lines") or args.get("Поручения") or []
    lines: list[dict[str, Any]] = []
    if isinstance(lines_in, list) and lines_in:
        for index, raw in enumerate(lines_in, start=1):
            if not isinstance(raw, dict):
                continue
            executor_key = str(raw.get("executor_key") or raw.get("ОтветственноеЛицо_Key") or "").strip()
            executor = str(raw.get("executor") or "").strip()
            if executor and not executor_key:
                executor_key = resolve_user(executor)["ref_key"]
            line: dict[str, Any] = {
                "LineNumber": str(raw.get("line") or raw.get("LineNumber") or index),
                "Мероприятие": str(raw.get("text") or raw.get("Мероприятие") or topic),
                "Приоритет": str(raw.get("priority") or raw.get("Приоритет") or ""),
            }
            line_due = str(raw.get("due") or raw.get("СрокИсполнения") or due).strip()
            if line_due:
                parsed = _parse_day(line_due)
                if parsed is not None:
                    line["СрокИсполнения"] = _odata_datetime(parsed)
            if executor_key:
                line["ОтветственноеЛицо_Key"] = executor_key
            lines.append(line)
    if not lines:
        lines = [{"LineNumber": "1", "Мероприятие": topic, "Приоритет": ""}]
        if due:
            parsed = _parse_day(due)
            if parsed is not None:
                lines[0]["СрокИсполнения"] = _odata_datetime(parsed)
    body: dict[str, Any] = {
        "Date": _odata_datetime(datetime.now()),
        "ОЧем": topic,
        "Основание": str(args.get("basis") or args.get("Основание") or "Устное поручение"),
        "Основание_Type": "Edm.String",
        "Руководитель_Key": customer_key,
        "Статус": str(args.get("status") or "Создано"),
        "Поручения": lines,
    }
    if due:
        parsed = _parse_day(due)
        if parsed is not None:
            body["СрокПолногоУстраненияНарушений"] = _odata_datetime(parsed)
    for src, dest in (
        ("secretary_key", "СекретарьРК_Key"),
        ("reporter_key", "КтоДоложитОЗавершенииМероприятий_Key"),
        ("organization_key", "Организация_Key"),
    ):
        value = str(args.get(src) or args.get(dest) or "").strip()
        if value:
            body[dest] = value
    secretary = str(args.get("secretary") or "").strip()
    if secretary and "СекретарьРК_Key" not in body:
        body["СекретарьРК_Key"] = resolve_user(secretary)["ref_key"]
    reporter = str(args.get("reporter") or "").strip()
    if reporter and "КтоДоложитОЗавершенииМероприятий_Key" not in body:
        body["КтоДоложитОЗавершенииМероприятий_Key"] = resolve_user(reporter)["ref_key"]
    return body


def build_update_body(args: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    status = str(args.get("status") or args.get("Статус") or "").strip()
    if status:
        body["Статус"] = status
    due = str(args.get("due") or args.get("СрокПолногоУстраненияНарушений") or "").strip()
    if due:
        parsed = _parse_day(due)
        if parsed is not None:
            body["СрокПолногоУстраненияНарушений"] = _odata_datetime(parsed)
    topic = str(args.get("topic") or args.get("ОЧем") or "").strip()
    if topic:
        body["ОЧем"] = topic
    lines_in = args.get("lines") or args.get("Поручения")
    if isinstance(lines_in, list) and lines_in:
        rebuilt: list[dict[str, Any]] = []
        for index, raw in enumerate(lines_in, start=1):
            if not isinstance(raw, dict):
                continue
            executor_key = str(raw.get("executor_key") or raw.get("ОтветственноеЛицо_Key") or "").strip()
            executor = str(raw.get("executor") or "").strip()
            if executor and not executor_key:
                executor_key = resolve_user(executor)["ref_key"]
            line: dict[str, Any] = {
                "LineNumber": str(raw.get("line") or raw.get("LineNumber") or index),
                "Мероприятие": str(raw.get("text") or raw.get("Мероприятие") or ""),
                "Приоритет": str(raw.get("priority") or raw.get("Приоритет") or ""),
            }
            line_due = str(raw.get("due") or raw.get("СрокИсполнения") or "").strip()
            if line_due:
                parsed = _parse_day(line_due)
                if parsed is not None:
                    line["СрокИсполнения"] = _odata_datetime(parsed)
            if executor_key:
                line["ОтветственноеЛицо_Key"] = executor_key
            rebuilt.append(line)
        body["Поручения"] = rebuilt
    if not body:
        raise AssignmentError("Dlya update nuzhen status, due ili lines")
    return body


def handle_assignments_write(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    _ = actor_fio, actor_user_id
    action = str(args.get("action") or "update").strip().casefold()
    if action == "create":
        body = build_create_body(args)
        result = _odata_post({"entity": ASSIGNMENT_ENTITY, "body": body})
        return {
            "summary": "Sozdano poruchenie v 1C (zhdi nomer AST00)",
            "entity": ASSIGNMENT_ENTITY,
            "body": body,
            **result,
        }
    if action in {"update", "update_status", "update_due", "reassign"}:
        ref_key = str(args.get("ref_key") or args.get("Ref_Key") or "").strip()
        number = str(args.get("number") or "").strip()
        if not ref_key and number:
            card = _get_assignment({"number": number})
            ref_key = str((card.get("assignment") or {}).get("ref_key") or "")
        if not ref_key:
            raise AssignmentError("Dlya update nuzhen number ili ref_key")
        body = build_update_body(args)
        result = _odata_patch({"entity": ASSIGNMENT_ENTITY, "ref_key": ref_key, "body": body})
        return {
            "summary": f"Obnovleno poruchenie {number or ref_key}",
            "entity": ASSIGNMENT_ENTITY,
            "ref_key": ref_key,
            "body": body,
            **result,
        }
    if action in {"comment_task", "return_task"}:
        ref_key = str(args.get("task_ref_key") or args.get("ref_key") or "").strip()
        comment = str(args.get("comment") or args.get("РезультатВыполнения") or "").strip()
        if not ref_key:
            raise AssignmentError("Dlya comment_task nuzhen task_ref_key")
        if not comment:
            raise AssignmentError("Dlya comment_task nuzhen comment")
        body = {"РезультатВыполнения": comment}
        result = _odata_patch({"entity": TASK_ENTITY, "ref_key": ref_key, "body": body})
        return {
            "summary": "Kommentariy zapisan v zadachu ispolnitelya",
            "entity": TASK_ENTITY,
            "ref_key": ref_key,
            "body": body,
            **result,
        }
    raise AssignmentError("action: create | update | comment_task")


def stub_assignments(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    action = str(args.get("action") or "list").strip().casefold()
    row = {
        "number": "АСТ00-00001",
        "ref_key": "00000000-0000-0000-0000-000000000001",
        "date": "2026-09-10T09:00:00",
        "posted": True,
        "status": "ВРаботе",
        "open": True,
        "topic": "Stub poruchenie Action Tracker",
        "basis": "Ustnoe rasporyazhenie",
        "customer": str(args.get("customer") or "Amural I.B."),
        "customer_key": "",
        "secretary": "",
        "reporter": "",
        "organization": "",
        "due": "2026-09-20T00:00:00",
        "weekly_report_date": "",
        "final_report_date": "",
        "overdue": False,
        "lines": [
            {
                "line": 1,
                "text": "Podgotovit otchet",
                "due": "2026-09-20T00:00:00",
                "executor": "Ivanov",
                "executor_key": "",
                "priority": "Vysokiy",
                "overdue": False,
            }
        ],
        "files": [],
    }
    if action == "get":
        return {"summary": "stub assignment card", "assignment": row, "count": 1, "source": "stub"}
    if action == "files":
        return {"summary": "stub files", "files": [], "count": 0, "source": "stub"}
    if action == "download":
        from app.services.onec_artifacts import stub_download_artifact

        return stub_download_artifact(args)
    if action == "tasks":
        return {
            "summary": "stub tasks",
            "tasks": [],
            "count": 0,
            "source": "stub",
            "hint": "Use action=list for AST00 journal. There is no 1C task named Check assignments.",
        }
    if action in {"protocols", "protocol"}:
        return {"summary": "stub protocols", "protocols": [], "count": 0, "source": "stub"}
    return {
        "summary": "stub: porucheniya 1C",
        "entity": ASSIGNMENT_ENTITY,
        "number_series": "АСТ00",
        "count": 1,
        "assignments": [row],
        "source": "stub",
    }


def stub_assignments_write(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    action = str(args.get("action") or "update").strip().casefold()
    return {
        "summary": f"stub assignment write ({action})",
        "updated": True,
        "source": "stub",
        "action": action,
    }


PROBE_MARK = "CONSTRUCTOR_PROBE"
PROBE_FROM_STATUS = "Создано"
PROBE_TO_STATUS = "ВРаботе"


def is_probe_topic(topic: str) -> bool:
    return PROBE_MARK in str(topic or "").upper().replace(" ", "")


def build_probe_topic(workflow_id: str = "") -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tail = str(workflow_id or "").strip()[:12]
    return f"{PROBE_MARK} {tail} {stamp}".strip()


def _assignment_ref_from_write(result: dict[str, Any]) -> tuple[str, str]:
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    if not data:
        data = result
    ref_key = str(
        data.get("Ref_Key")
        or result.get("erp_document_id")
        or result.get("ref_key")
        or ""
    ).strip()
    number = str(data.get("Number") or result.get("number") or "").strip()
    return ref_key, number


def mark_assignment_deleted(ref_key: str) -> None:
    if not _looks_like_guid(ref_key):
        return
    try:
        _odata_patch(
            {"entity": ASSIGNMENT_ENTITY, "ref_key": ref_key, "body": {"Posted": False}}
        )
    except Exception:  # noqa: BLE001
        pass
    _odata_patch(
        {
            "entity": ASSIGNMENT_ENTITY,
            "ref_key": ref_key,
            "body": {"DeletionMark": True},
        }
    )


def list_probe_assignments(*, customer_key: str = "", limit: int = 20) -> list[dict[str, Any]]:
    parts = ["DeletionMark eq false", f"substringof('{PROBE_MARK}', ОЧем)"]
    if customer_key and _looks_like_guid(customer_key):
        parts.append(f"Руководитель_Key eq guid'{customer_key}'")
    result = _odata_get(
        {"entity": ASSIGNMENT_ENTITY, "top": max(1, min(limit, 50)), "filter": " and ".join(parts)}
    )
    return [row for row in (result.get("value") or []) if isinstance(row, dict)]


def sweep_probe_assignments(*, customer_key: str = "") -> int:
    removed = 0
    for row in list_probe_assignments(customer_key=customer_key):
        topic = str(row.get("ОЧем") or "")
        if not is_probe_topic(topic):
            continue
        key = str(row.get("Ref_Key") or "")
        try:
            mark_assignment_deleted(key)
            removed += 1
        except Exception:  # noqa: BLE001
            continue
    return removed


def assignment_write_recipe(
    *,
    from_status: str = PROBE_FROM_STATUS,
    to_status: str = PROBE_TO_STATUS,
    source: str = "odata",
    verified: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    fields = list(verified or [])
    if not fields and (from_status or to_status):
        fields = [{"field": "Статус", "from": from_status, "to": to_status}]
    return {
        "entity": ASSIGNMENT_ENTITY,
        "tool": "onec.erp_assignments_write",
        "create": {
            "action": "create",
            "fields": ["ОЧем", "Основание", "Руководитель_Key", "Статус", "Поручения"],
        },
        "update_status": {
            "action": "update",
            "field": "Статус",
            "via": "odata_patch",
        },
        "delete": {"via": "DeletionMark"},
        "verified_status_from": from_status,
        "verified_status_to": to_status,
        "verified": fields,
        "source": source,
    }


def stub_write_probe(args: dict[str, Any], **_: Any) -> dict[str, Any]:
    recipe = assignment_write_recipe(source="stub")
    return {
        "ok": True,
        "cleaned": True,
        "source": "stub",
        "summary": "stub write probe: create -> status -> delete",
        "recipe": recipe,
        "test_number": "АСТ00-PROBE",
        "test_left": False,
        **recipe,
    }


def probe_assignment_write(
    args: dict[str, Any],
    *,
    actor_fio: str = "",
    actor_user_id: str = "",
    **_: Any,
) -> dict[str, Any]:
    """Create a marked test card, apply requested changes, remember the call, delete it."""
    from app.services.onec_tools import odata_configured

    if not odata_configured():
        return stub_write_probe(args)
    _ = actor_user_id
    customer = str(args.get("customer") or actor_fio or "").strip()
    workflow_id = str(args.get("workflow_id") or args.get("agent_id") or "").strip()
    raw_changes = args.get("changes")
    if isinstance(raw_changes, list) and raw_changes:
        changes = {str(item).strip().casefold() for item in raw_changes if str(item).strip()}
    else:
        changes = {"status"}
    need_status = bool(changes & {"status", "update"}) or not (changes & {"due", "create"})
    need_due = bool(changes & {"due"})
    if "create" in changes and not (changes & {"status", "update", "due"}):
        need_status = False
    topic = build_probe_topic(workflow_id)
    created_key = ""
    try:
        if customer:
            resolved = resolve_user(customer)
            customer_key = resolved["ref_key"]
            customer = resolved["fio"]
        else:
            raise AssignmentError(
                "Dlya probe nuzhen customer ili FIO sessii: sozdat testovoe poruchenie"
            )
        sweep_probe_assignments(customer_key=customer_key)
        created = handle_assignments_write(
            {
                "action": "create",
                "topic": topic,
                "basis": PROBE_MARK,
                "customer_key": customer_key,
                "status": PROBE_FROM_STATUS,
                "lines": [{"text": topic}],
            }
        )
        created_key, number = _assignment_ref_from_write(created)
        if not created_key:
            raise AssignmentError("Create ne vernul Ref_Key")
        card = _get_assignment({"ref_key": created_key})
        item = card.get("assignment") or {}
        number = str(item.get("number") or number)
        before = str(item.get("status") or PROBE_FROM_STATUS)
        verified: list[dict[str, str]] = []
        after = before
        if need_status:
            handle_assignments_write(
                {
                    "action": "update",
                    "ref_key": created_key,
                    "status": PROBE_TO_STATUS,
                }
            )
            again = _get_assignment({"ref_key": created_key})
            after = str((again.get("assignment") or {}).get("status") or "")
            if after != PROBE_TO_STATUS:
                raise AssignmentError(
                    f"Status ne smenilsya: zhili {before}, stalo {after or 'pust'}"
                )
            verified.append({"field": "Статус", "from": before, "to": after})
        if need_due:
            due_to = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
            handle_assignments_write(
                {
                    "action": "update",
                    "ref_key": created_key,
                    "due": due_to,
                }
            )
            due_card = _get_assignment({"ref_key": created_key})
            due_after = str((due_card.get("assignment") or {}).get("due") or "")
            if due_to not in due_after:
                raise AssignmentError(
                    f"Srok ne smenilsya: zhili {due_after or 'pust'}, zhdali {due_to}"
                )
            verified.append(
                {
                    "field": "СрокПолногоУстраненияНарушений",
                    "from": str(item.get("due") or ""),
                    "to": due_after,
                }
            )
        mark_assignment_deleted(created_key)
        recipe = assignment_write_recipe(
            from_status=before if need_status else "",
            to_status=after if need_status else "",
            verified=verified,
        )
        bits = [f"created {number or created_key}"]
        for item in verified:
            bits.append(f"{item['field']} {item.get('from') or '-'} -> {item.get('to') or '-'}")
        bits.append("deleted")
        return {
            "ok": True,
            "cleaned": True,
            "source": "odata",
            "summary": "Write probe ok: " + ", ".join(bits),
            "recipe": recipe,
            "test_number": number,
            "test_ref_key": created_key,
            "test_left": False,
            "customer": customer,
            **recipe,
        }
    except Exception as exc:  # noqa: BLE001
        cleaned = False
        if created_key:
            try:
                mark_assignment_deleted(created_key)
                cleaned = True
            except Exception:  # noqa: BLE001
                cleaned = False
        try:
            sweep_probe_assignments()
        except Exception:  # noqa: BLE001
            pass
        return {
            "ok": False,
            "cleaned": cleaned,
            "source": "odata",
            "summary": f"Write probe failed: {exc}",
            "error": str(exc),
            "test_left": bool(created_key) and not cleaned,
            "recipe": {},
        }
