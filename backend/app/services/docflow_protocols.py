"""Журнал протоколов совещаний 1С (Document_ТД_Протокол) для вкладки «Документооборот»."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any
from urllib.parse import quote

from app.services.docflow_document_tasks import fio_matches, normalize_fio

logger = logging.getLogger(__name__)

ENTITY = "Document_ТД_Протокол"
FILES_ENTITY = "Catalog_ТД_ПротоколПрисоединенныеФайлы"
ACCESS_ENTITY = "Catalog_ТД_ГрифыДоступа"
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
_GUID_IN_TEXT_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_SECRET_RE = re.compile(r"конфиденц|секрет|тайн|дсп|служебного пользования", re.IGNORECASE)
_DEFAULT_PAGE = 40
_MAX_PAGE = 100
_NAME_CHUNK = 25
_PEOPLE_CATALOGS = ("Catalog_Пользователи", "Catalog_ФизическиеЛица")
STATUSES = {"Подготовлен": "Подготовлен", "НаИсполнении": "На исполнении", "Закрыт": "Закрыт"}
KINDS = {"Отчетное": "Отчётное", "Внеплановое": "Внеплановое", "Селекторное": "Селекторное"}
# Признака выполнения у строк задач протокола в ERP нет, поэтому у них статусы только эти два.
TASK_OVERDUE = "Просрочена"
TASK_OPEN = "Поставлена"
# Выполнение знает только Документооборот: задачи «Исполнить задачу №N» с предметом-протоколом.
TASK_DONE = "Выполнена"
_DO_TARGET_TYPE = "DMInternalDocument"
_DO_TIMEOUT_SEC = 45.0
_DO_LIMIT = 300
_DO_TASK_NO_RE = re.compile(r"задач[уаи]?\s*№\s*(\d+)", re.IGNORECASE)
_dump_index: tuple[float, dict[str, list[dict[str, Any]]]] | None = None

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


def _own_fios(args: dict[str, Any]) -> list[str]:
    raw = args.get("delegate_fios")
    delegates = raw if isinstance(raw, (list, tuple)) else str(raw or "").split(";")
    names = [str(args.get("fio") or ""), *(str(item) for item in delegates)]
    return [name.strip() for name in names if name.strip()]


def is_own(row: dict[str, Any], fios: list[str]) -> bool:
    """Свой протокол — где пользователь подготовил документ или назначен ответственным."""
    people = [_nav(row, "Подготовил"), _nav(row, "Ответственный")]
    return any(fio_matches(person, fio) for person in people if person for fio in fios)


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
        "time_start": start,
        "time_end": finish,
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
        "secret": is_secret(row),
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
    fios = _own_fios(args)
    # Конфиденциальный протокол показываем только его автору или ответственному — с пометкой «секретно».
    allowed = [row for row in raw if not is_secret(row) or is_own(row, fios)]
    rows = [_row_view(row) for row in allowed]
    return {
        "summary": f"Протоколы: {len(rows)}",
        "rows": rows,
        "count": len(rows),
        "skip": skip,
        "next_skip": skip + len(raw),
        "has_more": len(raw) >= top,
        "hidden_secret": len(raw) - len(allowed),
        "own_secret": sum(1 for row in rows if row["secret"]),
        "statuses": [{"code": code, "label": label} for code, label in STATUSES.items()],
        "kinds": [{"code": code, "label": label} for code, label in KINDS.items()],
    }


def _date(value: Any) -> str:
    return _text(value)


def _person(key: Any) -> str:
    return _names.get(_text(key), "")


def _files(ref: str) -> dict[str, dict[str, Any]]:
    filt = _q(f"ВладелецФайла_Key eq guid'{ref}' and DeletionMark eq false")
    try:
        data = _odata(
            f"{FILES_ENTITY}?$format=json&$top=100&$filter={filt}"
            "&$select=Ref_Key,Description,Расширение,Размер,ДатаСоздания,ПодписанЭП"
        )
    except DocflowProtocolError as exc:
        logger.warning("protocol %s files failed: %s", ref, str(exc)[:200])
        return {}
    files: dict[str, dict[str, Any]] = {}
    for row in data.get("value") or []:
        if not isinstance(row, dict):
            continue
        key = _text(row.get("Ref_Key"))
        if not key:
            continue
        extension = _text(row.get("Расширение"))
        name = _text(row.get("Description"))
        files[key] = {
            "id": key,
            "name": f"{name}.{extension}" if name and extension else name or extension,
            "extension": extension,
            "size": int(_text(row.get("Размер")) or 0),
            "created": _text(row.get("ДатаСоздания")),
            "signed": _flag(row.get("ПодписанЭП")),
        }
    return files


def _file_keys(value: Any) -> list[str]:
    """Файл строки задачи лежит списком значений XDTO со ссылками на присоединённые файлы протокола."""
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        text = base64.b64decode(raw).decode("utf-8", "replace")
    except (ValueError, binascii.Error):
        return []
    return [key for key in _GUID_IN_TEXT_RE.findall(text) if key != _EMPTY_GUID]


def _task_view(item: dict[str, Any], *, permanent: bool, files: dict[str, dict[str, Any]], today: str) -> dict[str, Any]:
    """ДатаФактическогоИсполнения в ERP — это срок исполнения задачи, а не отметка о выполнении."""
    due = _date(item.get("ДатаФактическогоИсполнения"))
    overdue = bool(due and due[:10] < today)
    return {
        "line": int(item.get("LineNumber") or 0),
        "n": int(item.get("НомерПунктаПротокола") or item.get("LineNumber") or 0),
        "text": _text(item.get("Задача")),
        "responsible": _text(item.get("Ответственный")) if permanent else _person(item.get("Ответственный_Key")),
        "responsible_key": "" if permanent else _text(item.get("Ответственный_Key")),
        "author": _person(item.get("Автор_Key")),
        "set_at": _date(item.get("ДатаПостановкиЗадачи")),
        "due": due,
        "overdue": overdue,
        "status": TASK_OVERDUE if overdue else TASK_OPEN,
        "priority": _text(item.get("Приоритет")),
        "sent": _flag(item.get("Отправлена")),
        "note": _text(item.get("Примечание")),
        "files": [files[key] for key in _file_keys(item.get("Файл_Base64Data")) if key in files],
        "source": "erp",
        "executed": False,
    }


def _do_request(config: Any, ref: str) -> list[dict[str, Any]]:
    """Все задачи ДО (и исполненные) с предметом-протоколом: GUID протокола в ДО тот же, что в ERP."""
    from app.tools.onec.dok_soap import bool_value, condition, execute_dm, object_id_value, parse_tasks

    columns = ("name", "performer", "author", "beginDate", "dueDate", "executed", "description", "businessProcessStep", "target")
    root = execute_dm(
        config,
        '<dm:request xsi:type="dm:DMGetObjectListRequest">'
        "<dm:type>DMBusinessProcessTask</dm:type>"
        "<dm:query>"
        f"{condition('withExecuted', bool_value(True))}"
        f"{condition('target', object_id_value(ref, _DO_TARGET_TYPE))}"
        f"<dm:limit>{_DO_LIMIT}</dm:limit>"
        + "".join(f"<dm:columnSet>{name}</dm:columnSet>" for name in columns)
        + "</dm:query></dm:request>",
        timeout=_DO_TIMEOUT_SEC,
    )
    rows = parse_tasks(root)
    matched = [row for row in rows if str(row.get("target_id") or "").casefold() == ref.casefold()]
    if len(rows) >= _DO_LIMIT and not matched:
        raise RuntimeError("Документооборот не применил отбор по предмету")
    return matched


def _dump_open_rows(refs: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Открытые задачи из последней выгрузки ДО — когда сессии с паролем нет."""
    global _dump_index
    from app.tools.onec.dok_soap import _cache_dir, _dump_rows

    try:
        newest = max(_cache_dir().glob("*.json"), key=lambda path: path.stat().st_mtime)
        mtime = newest.stat().st_mtime
        if not _dump_index or _dump_index[0] != mtime:
            data = json.loads(newest.read_text(encoding="utf-8"))
            payload = data.get("payload") if isinstance(data, dict) else None
            index: dict[str, list[dict[str, Any]]] = {}
            for row in _dump_rows(payload if isinstance(payload, dict) else {}):
                if str(row.get("target_type") or "") == _DO_TARGET_TYPE:
                    index.setdefault(str(row.get("target_id") or "").casefold(), []).append(row)
            _dump_index = (mtime, index)
    except (OSError, ValueError) as exc:
        logger.warning("protocol docflow dump read failed: %s", str(exc)[:200])
        return {ref: [] for ref in refs}
    return {ref: list(_dump_index[1].get(ref.casefold(), [])) for ref in refs}


def _docflow_tasks(args: dict[str, Any], refs: list[str]) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """Задачи ДО по протоколам под сессией пользователя; иначе — открытые из выгрузки с пометкой."""
    from app.tools.onec.docflow_inbox_fetch import _is_soap_http_auth_error, _soap_login_attempts
    from app.tools.onec.dok_soap import load_config

    refs = [ref for ref in dict.fromkeys(refs) if _GUID_RE.match(ref) and ref != _EMPTY_GUID]
    if not refs:
        return {}, ""
    error = "нет пароля 1С с экрана входа"
    for username, password in _soap_login_attempts(args) if str(args.get("password") or "").strip() else []:
        try:
            config = load_config(username=username, password=password)
            with ThreadPoolExecutor(max_workers=len(refs)) as pool:
                futures = {ref: pool.submit(_do_request, config, ref) for ref in refs}
                return {ref: future.result() for ref, future in futures.items()}, ""
        except (RuntimeError, ValueError, OSError, ET.ParseError) as exc:
            error = str(exc)
            if _is_soap_http_auth_error(error):
                continue
            logger.warning("protocol docflow tasks failed: %s", error[:300])
            break
    note = f"Документооборот недоступен ({error[:160]}) — показаны только открытые задачи из последней выгрузки"
    return _dump_open_rows(refs), note


def _docflow_task_views(rows: list[dict[str, Any]], today: str) -> list[dict[str, Any]]:
    """Как список в форме 1С: строка на пункт и исполнителя; перенос срока в ДО — новая задача той же строки."""
    groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
    for row in rows:
        name, step = _text(row.get("name")), _text(row.get("step"))
        if not (step.startswith("Исполн") or name.startswith("Исполнить")):
            continue
        match = _DO_TASK_NO_RE.search(name)
        groups.setdefault((int(match.group(1)) if match else 0, normalize_fio(_text(row.get("performer")))), []).append(row)
    views: list[dict[str, Any]] = []
    for (number, _), items in groups.items():
        items.sort(key=lambda item: _text(item.get("begin")))
        first, last = items[0], items[-1]
        executed = bool(last.get("executed"))
        due = _text(last.get("due"))
        overdue = bool(not executed and due and due[:10] < today)
        text = next((_text(item.get("description")) for item in reversed(items) if _text(item.get("description"))), "")
        views.append(
            {
                "line": 0,
                "n": number,
                "text": text or _text(last.get("name")),
                "responsible": _text(last.get("performer")),
                "responsible_key": "",
                "author": _text(last.get("author")),
                "set_at": _text(first.get("begin")),
                "due": due,
                "overdue": overdue,
                "status": TASK_DONE if executed else TASK_OVERDUE if overdue else TASK_OPEN,
                "priority": "",
                "sent": True,
                "note": f"Срок переносился: {len(items) - 1}" if len(items) > 1 else "",
                "files": [],
                "source": "docflow",
                "executed": executed,
            }
        )
    views.sort(key=lambda item: (item["n"], item["responsible"]))
    return views


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


def _access_options() -> list[str]:
    try:
        data = _odata(
            f"{ACCESS_ENTITY}?$format=json&$top=50&$filter={_q('DeletionMark eq false')}&$select=Description"
        )
    except DocflowProtocolError as exc:
        logger.warning("protocol access options failed: %s", str(exc)[:200])
        return []
    return sorted({_text(row.get("Description")) for row in data.get("value") or [] if isinstance(row, dict)} - {""})


def _edit_view(
    view: dict[str, Any],
    fio: str,
    tables: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Карандаш — только автору (Подготовил); сервер при записи проверяет то же по ФИО из токена."""
    from app.services.meeting_protocol_write import DRAFT_STATUS, task_table_block

    author = bool(fio and view["prepared_by"] and fio_matches(view["prepared_by"], fio))
    reason = ""
    if author and (view["posted"] or view["status_code"] not in ("", DRAFT_STATUS)):
        reason = f"Протокол уже {'проведён' if view['posted'] else 'в работе'} (статус «{view['status']}») — правки только в 1С"
    return {
        "author": author,
        "allowed": author and not reason,
        "reason": reason,
        "control_block": task_table_block(tables["control"]) if author else "",
        "assigned_block": task_table_block(tables["assigned"]) if author else "",
        "access_options": _access_options() if author and not reason else [],
    }


def protocol_card(args: dict[str, Any]) -> dict[str, Any]:
    ref = str(args.get("ref_key") or args.get("id") or "").strip()
    if not _GUID_RE.match(ref):
        raise DocflowProtocolError("Нужен Ref_Key протокола")
    # $expand работает только в списке: одиночный GET по guid его не принимает.
    found = _odata(_list_path([f"Ref_Key eq guid'{ref}'"], top=1, skip=0, with_parts=True)).get("value") or []
    row = found[0] if found and isinstance(found[0], dict) else {}
    if not row:
        raise DocflowProtocolError("1С не вернула протокол")
    if is_secret(row) and not is_own(row, _own_fios(args)):
        raise DocflowProtocolError("Протокол с ограниченным грифом доступа — открыт только автору и ответственному.")

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
    files = _files(ref)
    today = date.today().isoformat()
    # Вкладки как в 1С: постоянные задачи — «Задачи для контроля», переменные — «Поставленные задачи».
    control = [_task_view(item, permanent=True, files=files, today=today) for item in permanent]
    assigned = [_task_view(item, permanent=False, files=files, today=today) for item in variable]
    # Верхний список этих вкладок форма 1С берёт из Документооборота: на контроле — задачи
    # по протоколу-основанию (прошлое совещание), поставленные — задачи по этому протоколу.
    base_ref = _text(row.get("ДокументОснование")) if "ТД_Протокол" in _text(row.get("ДокументОснование_Type")) else ""
    docflow, docflow_note = _docflow_tasks(args, [ref, base_ref])
    control_docflow = _docflow_task_views(docflow.get(base_ref, []), today) if base_ref else []
    assigned_docflow = _docflow_task_views(docflow.get(ref, []), today)
    base_number = ""
    if base_ref:
        try:
            base_rows = _odata(
                f"{ENTITY}?$format=json&$top=1&$filter={_q(f'Ref_Key eq guid{chr(39)}{base_ref}{chr(39)}')}&$select=Number,Date"
            ).get("value") or []
            base_number = _text(base_rows[0].get("Number")) if base_rows else ""
        except DocflowProtocolError as exc:
            logger.warning("protocol %s base number failed: %s", ref, str(exc)[:200])
    control_all, assigned_all = control_docflow + control, assigned_docflow + assigned
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
                "files": [files[key] for key in _file_keys(item.get("Файл_Base64Data")) if key in files],
            }
            for item in agenda
        ],
        "decisions": decision_rows,
        "control_tasks": control,
        "assigned_tasks": assigned,
        "control_docflow": control_docflow,
        "assigned_docflow": assigned_docflow,
        "base_protocol": {"id": base_ref, "number": base_number} if base_ref else None,
        "docflow_note": docflow_note,
        "files": sorted(files.values(), key=lambda item: item["created"], reverse=True),
        "period_done": _plan_rows(period_done, text_key="Задача"),
        "period_plan": _plan_rows(period_plan, text_key="Задача"),
        "plan_fact": _plan_rows(plan_fact, text_key="ОтчетОВыполненнойРаботе"),
        "edit": _edit_view(
            view,
            str(args.get("fio") or "").strip(),
            {"control": permanent, "assigned": variable},
        ),
        "stats": {
            "decisions": len(decision_rows),
            "decisions_done": sum(1 for item in decision_rows if item["done_at"] and not item["cancelled"]),
            "decisions_cancelled": sum(1 for item in decision_rows if item["cancelled"]),
            "control_tasks": len(control_all),
            "control_overdue": sum(1 for item in control_all if item["overdue"]),
            "control_done": sum(1 for item in control_all if item["executed"]),
            "assigned_tasks": len(assigned_all),
            "assigned_overdue": sum(1 for item in assigned_all if item["overdue"]),
            "assigned_done": sum(1 for item in assigned_all if item["executed"]),
            "files": len(files),
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
