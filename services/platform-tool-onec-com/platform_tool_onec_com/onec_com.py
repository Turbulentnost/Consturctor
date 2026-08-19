"""1C ERP COM — V83.COMConnector session (32-bit Python required)."""

from __future__ import annotations

import os
import struct
import uuid
from typing import Any
from urllib.parse import urlparse

_COM_CONNECTOR_PROGIDS = (
    "V83.COMConnector.1",
    "V83.COMConnector",
    "V83c.COMConnector",
)

_APPLICATION_PROGIDS = (
    "V83.Application",
    "V83c.Application",
    "V82.Application",
)


def python_bitness() -> int:
    return struct.calcsize("P") * 8


def require_32bit_python() -> None:
    if python_bitness() != 32:
        raise RuntimeError(
            f"ONEC_COM_SERVICE_REQUIRES_32BIT_PYTHON: current python is {python_bitness()}-bit. "
            "Start with: py -3.12-32 -m platform_tool_onec_com.main "
            "(scripts\\start_onec_com_service.cmd)"
        )


def _strip_env_value(raw: str) -> str:
    value = (raw or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _server_ref_from_env() -> tuple[str, str]:
    """Derive COM server/ref from ONEC_COM_* or OData URL hostname (without HTTP port)."""
    base = (os.environ.get("ODATA_BASE_URL") or os.environ.get("ONEC_COM_ODATA_URL") or "").strip()
    if not base:
        return "", "erp_pm"
    parsed = urlparse(base)
    host = parsed.hostname or ""
    parts = [part for part in (parsed.path or "").split("/") if part]
    ref = parts[0] if parts else "erp_pm"
    return host, ref


def build_connection_string(*, override: str = "") -> str:
    explicit = _strip_env_value(override or os.environ.get("ONEC_COM_CONNECTION_STRING") or "")
    if explicit:
        return explicit if explicit.endswith(";") else f"{explicit};"

    server = _strip_env_value(os.environ.get("ONEC_COM_SERVER") or "")
    ref = _strip_env_value(os.environ.get("ONEC_COM_REF") or os.environ.get("ONEC_COM_IB") or "")
    if not server or not ref:
        parsed_server, parsed_ref = _server_ref_from_env()
        server = server or parsed_server
        ref = ref or parsed_ref

    user = _strip_env_value(
        os.environ.get("ONEC_COM_USER")
        or os.environ.get("ERP_LOGIN")
        or os.environ.get("ONEC_USER")
        or ""
    )
    password = _strip_env_value(
        os.environ.get("ONEC_COM_PASSWORD")
        or os.environ.get("ERP_PASSWORD")
        or os.environ.get("ONEC_PASSWORD")
        or ""
    )

    parts: list[str] = []
    if server:
        parts.append(f'Srvr="{server}"')
    if ref:
        parts.append(f'Ref="{ref}"')
    if user:
        parts.append(f'Usr="{user}"')
    if password:
        parts.append(f'Pwd="{password}"')
    return ";".join(parts) + (";" if parts else "")


def get_current_user_name(app: Any) -> str:
    user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
    for attr in ("ПолноеИмя", "Name", "Имя"):
        value = str(getattr(user, attr, "") or "").strip()
        if value:
            return value
    return str(user)


def _safe_str(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.startswith("0001-01-01"):
        return ""
    if len(text) > limit:
        return text[: limit - 3] + "..."
    return text


def _ref_metadata_name(ref: Any) -> str:
    if ref is None:
        return ""
    try:
        md = ref.Метаданные()
        return str(getattr(md, "Имя", "") or getattr(md, "Name", "") or "")
    except Exception:
        return ""


def resolve_ref_info(ref: Any) -> dict[str, str]:
    if ref is None:
        return {}
    info: dict[str, str] = {"type": _ref_metadata_name(ref)}
    for attr in ("Номер", "Number", "Наименование", "Description", "Дата", "Date"):
        try:
            val = getattr(ref, attr, None)
            if val is None or val is False:
                continue
            if hasattr(val, "Наименование"):
                info[attr.lower()] = _safe_str(val.Наименование)
            else:
                info[attr.lower()] = _safe_str(val)
        except Exception:
            continue
    return info


def query_attached_files(app: Any, owner_ref: Any, *, metadata_name: str = "") -> list[dict[str, str]]:
    """Read attached files via catalog {MetadataName}ПрисоединенныеФайлы."""
    if owner_ref is None:
        return []

    meta = metadata_name or _ref_metadata_name(owner_ref)
    if not meta:
        return []

    catalog = f"{meta}ПрисоединенныеФайлы"
    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ 50
        Ф.Наименование КАК Name,
        Ф.Расширение КАК Ext,
        Ф.Размер КАК Size,
        Ф.Описание КАК Description,
        Ф.ДатаСоздания КАК Created,
        Ф.ТипХраненияФайла КАК StorageType,
        Ф.ПутьКФайлу КАК Path
        ИЗ Справочник.{catalog} КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref"""
    try:
        query = app.NewObject("Query", query_text)
        query.SetParameter("Ref", owner_ref)
        table = query.Execute().Unload()
    except Exception:
        return []

    files: list[dict[str, str]] = []
    for i in range(table.Count()):
        row = table.Get(i)
        files.append(
            {
                "name": _safe_str(getattr(row, "Name", "") or getattr(row, "Наименование", "")),
                "extension": _safe_str(getattr(row, "Ext", "") or getattr(row, "Расширение", "")),
                "size": _safe_str(getattr(row, "Size", "") or getattr(row, "Размер", "")),
                "description": _safe_str(getattr(row, "Description", "") or getattr(row, "Описание", ""), 1000),
                "created": _safe_str(getattr(row, "Created", "") or getattr(row, "ДатаСоздания", "")),
                "storage_type": _safe_str(getattr(row, "StorageType", "") or getattr(row, "ТипХраненияФайла", "")),
                "path": _safe_str(getattr(row, "Path", "") or getattr(row, "ПутьКФайлу", "")),
                "catalog": catalog,
            }
        )
    return files


def query_tasks_period(
    app: Any,
    *,
    date_from: str,
    date_to: str,
    mine_only: bool = True,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Query Задача.ЗадачаИсполнителя for [date_from, date_to) ISO dates."""
    from datetime import datetime

    limit = max(1, min(200, int(limit)))
    start = datetime.fromisoformat(date_from)
    end = datetime.fromisoformat(date_to)
    user_filter = ""
    if mine_only:
        user_name = get_current_user_name(app).replace('"', '""')
        user_filter = f'И Т.Исполнитель.Наименование = "{user_name}"'

    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ {limit}
        Т.Ссылка КАК Ref,
        Т.Номер КАК Number,
        Т.Наименование КАК Description,
        Т.Дата КАК Date,
        Т.СрокИсполнения КАК DueDate,
        Т.Исполнитель.Наименование КАК Executor,
        Т.Автор.Наименование КАК Author,
        Т.Выполнена КАК Done,
        Т.РезультатВыполнения КАК Result,
        Т.Предмет КАК Subject
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ Т.Дата >= ДАТАВРЕМЯ({start.year}, {start.month}, {start.day})
            И Т.Дата < ДАТАВРЕМЯ({end.year}, {end.month}, {end.day})
            {user_filter}
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
    table = app.NewObject("Query", query_text).Execute().Unload()
    rows: list[dict[str, Any]] = []
    for i in range(table.Count()):
        row = table.Get(i)
        subject_ref = getattr(row, "Subject", None) or getattr(row, "Предмет", None)
        subject_info = resolve_ref_info(subject_ref)
        item: dict[str, Any] = {
            "number": _safe_str(getattr(row, "Number", "") or getattr(row, "Номер", "")),
            "description": _safe_str(getattr(row, "Description", "") or getattr(row, "Наименование", "")),
            "date": _safe_str(getattr(row, "Date", "") or getattr(row, "Дата", "")),
            "due_date": _safe_str(getattr(row, "DueDate", "") or getattr(row, "СрокИсполнения", "")),
            "executor": _safe_str(getattr(row, "Executor", "") or getattr(row, "Исполнитель", "")),
            "author": _safe_str(getattr(row, "Author", "") or getattr(row, "Автор", "")),
            "done": _safe_str(getattr(row, "Done", "") or getattr(row, "Выполнена", "")),
            "result": _safe_str(getattr(row, "Result", "") or getattr(row, "РезультатВыполнения", "")),
            "subject": subject_info,
            "source": "erp_задача_исполнителя",
        }
        attachments: list[dict[str, str]] = []
        try:
            task_ref = getattr(row, "Ref", None)
            attachments.extend(query_attached_files(app, task_ref, metadata_name="ЗадачаИсполнителя"))
        except Exception:
            pass
        if subject_ref is not None and subject_info.get("type"):
            try:
                attachments.extend(query_attached_files(app, subject_ref, metadata_name=subject_info["type"]))
            except Exception:
                pass
        item["attachments"] = attachments
        rows.append(item)
    return rows


def get_task_details(app: Any, *, number: str) -> dict[str, Any]:
    safe_number = number.replace('"', '""')
    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ 1
        Т.Ссылка КАК Ref,
        Т.Номер КАК Number,
        Т.Наименование КАК Description,
        Т.Дата КАК Date,
        Т.СрокИсполнения КАК DueDate,
        Т.Исполнитель.Наименование КАК Executor,
        Т.Автор.Наименование КАК Author,
        Т.Выполнена КАК Done,
        Т.РезультатВыполнения КАК Result,
        Т.Предмет КАК Subject,
        Т.Описание КАК Details
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ Т.Номер = "{safe_number}\""""
    table = app.NewObject("Query", query_text).Execute().Unload()
    if not table.Count():
        return {"found": False, "number": number}

    row = table.Get(0)
    subject_ref = getattr(row, "Subject", None) or getattr(row, "Предмет", None)
    subject_info = resolve_ref_info(subject_ref)
    task_ref = getattr(row, "Ref", None)

    fields: dict[str, str] = {}
    for alias, attr in (
        ("number", "Number"),
        ("description", "Description"),
        ("date", "Date"),
        ("due_date", "DueDate"),
        ("executor", "Executor"),
        ("author", "Author"),
        ("done", "Done"),
        ("result", "Result"),
        ("details", "Details"),
    ):
        val = getattr(row, attr, None)
        if hasattr(val, "Наименование"):
            fields[alias] = _safe_str(val.Наименование)
        else:
            fields[alias] = _safe_str(val, 2000)

    attachments = query_attached_files(app, task_ref, metadata_name="ЗадачаИсполнителя")
    if subject_ref is not None and subject_info.get("type"):
        attachments.extend(query_attached_files(app, subject_ref, metadata_name=subject_info["type"]))

    return {
        "found": True,
        "number": number,
        "fields": fields,
        "subject": subject_info,
        "attachments": attachments,
    }


def read_attached_file_bytes(app: Any, file_ref: Any) -> bytes | None:
    """Read binary via server call; works when file volume is accessible to 1C server."""
    if file_ref is None:
        return None
    try:
        svc = app.РаботаСФайламиСлужебныйВызовСервера
        for method in ("ПолучитьДанныеФайла", "ДанныеФайла"):
            if not hasattr(svc, method):
                continue
            result = getattr(svc, method)(file_ref)
            for field in ("Данные", "ДвоичныеДанные", "BinaryData"):
                try:
                    val = getattr(result, field, None)
                    if val is not None and hasattr(val, "Получить"):
                        return bytes(val.Получить())
                except Exception:
                    continue
    except Exception:
        pass
    return None


def read_extracted_file_text(app: Any, file_ref: Any) -> str:
    """Fallback: indexed text from ТекстХранилище when binary volume is unavailable."""
    if file_ref is None:
        return ""
    try:
        obj = file_ref.ПолучитьОбъект()
        store = getattr(obj, "ТекстХранилище", None)
        if store is None:
            return ""
        store_obj = store.ПолучитьОбъект()
        for attr in ("Текст", "Text", "Value", "Данные"):
            val = getattr(store_obj, attr, None)
            if val:
                return _safe_str(val, 50000)
    except Exception:
        pass
    return ""


def get_incoming_correspondence(app: Any, *, number: str) -> dict[str, Any]:
    safe_number = number.replace('"', '""')
    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ 1
        Д.Ссылка КАК Ref,
        Д.Номер КАК Number,
        Д.Дата КАК DocDate,
        Д.Комментарий КАК Comment,
        Д.Организация.Наименование КАК Org,
        Д.Контрагент.Наименование КАК Counterparty,
        Д.Содержание КАК Content,
        Д.ТемаСлужебнойЗаписки КАК MemoSubject,
        Д.EmailОтправителяПисьма КАК EmailFrom,
        Д.EmailПолучателяПисьма КАК EmailTo,
        Д.Кому КАК MailTo,
        Д.НомерИсходящий КАК OutNumber,
        Д.ДатаИсходящая КАК OutDate,
        Д.Ответственный.Наименование КАК Responsible,
        Д.ТекстHTML КАК HtmlText
        ИЗ Документ.ТД_ВходящаяКорреспонденция КАК Д
        ГДЕ Д.Номер = "{safe_number}"
            И НЕ Д.ПометкаУдаления"""
    table = app.NewObject("Query", query_text).Execute().Unload()
    if not table.Count():
        return {"found": False, "number": number}

    row = table.Get(0)
    doc_ref = getattr(row, "Ref", None)
    fields: dict[str, str] = {}
    for alias, attr in (
        ("number", "Number"),
        ("date", "DocDate"),
        ("comment", "Comment"),
        ("org", "Org"),
        ("counterparty", "Counterparty"),
        ("content", "Content"),
        ("memo_subject", "MemoSubject"),
        ("email_from", "EmailFrom"),
        ("email_to", "EmailTo"),
        ("mail_to", "MailTo"),
        ("out_number", "OutNumber"),
        ("out_date", "OutDate"),
        ("responsible", "Responsible"),
        ("html_text", "HtmlText"),
    ):
        val = getattr(row, attr, None)
        if hasattr(val, "Наименование"):
            fields[alias] = _safe_str(val.Наименование, 5000)
        else:
            fields[alias] = _safe_str(val, 5000)

    attachments: list[dict[str, Any]] = []
    files_query = """ВЫБРАТЬ
        Ф.Ссылка КАК Ref,
        Ф.Наименование КАК Name,
        Ф.Расширение КАК Ext,
        Ф.Размер КАК Size,
        Ф.Описание КАК Description,
        Ф.ДатаСоздания КАК Created,
        Ф.ПутьКФайлу КАК Path,
        Ф.Том.ПолныйПутьWindows КАК VolumePath
        ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref"""
    fq = app.NewObject("Query", files_query)
    fq.SetParameter("Ref", doc_ref)
    ft = fq.Execute().Unload()
    for i in range(ft.Count()):
        frow = ft.Get(i)
        file_ref = getattr(frow, "Ref", None)
        name = _safe_str(getattr(frow, "Name", ""))
        ext = _safe_str(getattr(frow, "Ext", "")).lstrip(".")
        item: dict[str, Any] = {
            "name": name,
            "extension": ext,
            "size": _safe_str(getattr(frow, "Size", "")),
            "description": _safe_str(getattr(frow, "Description", "")),
            "created": _safe_str(getattr(frow, "Created", "")),
            "path": _safe_str(getattr(frow, "Path", "")),
            "volume_path": _safe_str(getattr(frow, "VolumePath", "")),
        }
        data = read_attached_file_bytes(app, file_ref)
        if data:
            item["binary_size"] = len(data)
        extracted = read_extracted_file_text(app, file_ref)
        if extracted:
            item["extracted_text"] = extracted
        attachments.append(item)

    return {
        "found": True,
        "number": number,
        "fields": fields,
        "attachments": attachments,
    }


def _rows_from_table(table: Any, *, source: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i in range(table.Count()):
        row = table.Get(i)
        rows.append(
            {
                "number": str(getattr(row, "Number", "") or getattr(row, "Номер", "") or ""),
                "description": str(
                    getattr(row, "Description", "") or getattr(row, "Наименование", "") or ""
                ),
                "date": str(getattr(row, "Date", "") or getattr(row, "Дата", "") or ""),
                "due_date": str(getattr(row, "DueDate", "") or getattr(row, "СрокИсполнения", "") or ""),
                "executor": str(getattr(row, "Executor", "") or getattr(row, "Исполнитель", "") or ""),
                "source": source,
            }
        )
    return rows


def _row_field(row: Any, *names: str) -> str:
    for name in names:
        value = getattr(row, name, None)
        if value not in (None, ""):
            return _safe_str(value, 2000)
    return ""


_READ_QUERY_PREFIXES = ("ВЫБРАТЬ", "SELECT")
_FORBIDDEN_QUERY_TOKENS = (
    "ИЗМЕНИТЬ",
    "УДАЛИТЬ",
    "ВСТАВИТЬ",
    "ОБНОВИТЬ",
    "DROP ",
    "INSERT ",
    "UPDATE ",
    "DELETE ",
    "CREATE ",
    "ALTER ",
)


def validate_readonly_query(query_text: str) -> str:
    text = (query_text or "").strip()
    if not text:
        raise ValueError("query_text is required")
    collapsed = " ".join(text.split())
    upper = collapsed.upper()
    if not any(upper.startswith(prefix) for prefix in _READ_QUERY_PREFIXES):
        raise ValueError("Only read-only queries (ВЫБРАТЬ/SELECT) are allowed")
    for token in _FORBIDDEN_QUERY_TOKENS:
        if token in f"{upper} ":
            raise ValueError(f"Forbidden token in query: {token.strip()}")
    return collapsed


def serialize_cell(value: Any) -> Any:
    if value is None or value is False:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (str, bytes)):
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
        text = text.strip()
        if text.startswith("0001-01-01") or text.startswith("0100-01-01"):
            return None
        return text[:4000]
    if hasattr(value, "year") and hasattr(value, "month"):
        return _safe_str(value, 64)
    if hasattr(value, "Наименование"):
        return _safe_str(getattr(value, "Наименование", ""), 500)
    if hasattr(value, "Number") or hasattr(value, "Номер"):
        return _safe_str(getattr(value, "Number", None) or getattr(value, "Номер", ""), 120)
    text = _safe_str(value, 500)
    if text.startswith("<COMObject"):
        return None
    return text


def unload_query_result(table: Any, *, limit: int = 200) -> dict[str, Any]:
    columns: list[str] = []
    if hasattr(table, "Columns"):
        columns = [table.Columns.Get(i).Name for i in range(table.Columns.Count())]
    rows: list[dict[str, Any]] = []
    max_rows = max(1, min(int(limit or 200), 500))
    for i in range(min(max_rows, table.Count())):
        row = table.Get(i)
        item: dict[str, Any] = {}
        if columns:
            for name in columns:
                item[name] = serialize_cell(getattr(row, name, None))
        else:
            item["value"] = serialize_cell(row)
        rows.append(item)
    return {"columns": columns, "rows": rows, "count": len(rows), "total": table.Count()}


def execute_query(
    app: Any,
    query_text: str,
    *,
    parameters: dict[str, Any] | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    validated = validate_readonly_query(query_text)
    query = app.NewObject("Query", validated)
    for key, value in (parameters or {}).items():
        if key:
            query.SetParameter(str(key), value)
    table = query.Execute().Unload()
    payload = unload_query_result(table, limit=limit)
    payload["query"] = validated[:500]
    return payload


_METADATA_KINDS = (
    "Documents",
    "Catalogs",
    "InformationRegisters",
    "Reports",
    "DataProcessors",
    "Tasks",
    "BusinessProcesses",
    "CommonModules",
)


def search_metadata(
    app: Any,
    *,
    pattern: str = "",
    kinds: list[str] | None = None,
    limit: int = 50,
) -> list[dict[str, str]]:
    needle = (pattern or "").strip().casefold()
    max_items = max(1, min(int(limit or 50), 200))
    selected = [k for k in (kinds or _METADATA_KINDS) if k in _METADATA_KINDS]
    if not selected:
        selected = list(_METADATA_KINDS)
    hits: list[dict[str, str]] = []
    md = app.Metadata
    for kind in selected:
        coll = getattr(md, kind, None)
        if coll is None:
            continue
        for i in range(coll.Count()):
            obj = coll.Get(i)
            name = str(getattr(obj, "Name", "") or "")
            synonym = str(getattr(obj, "Synonym", "") or "")
            blob = f"{name} {synonym}".casefold()
            if needle and needle not in blob:
                continue
            hits.append({"kind": kind, "name": name, "synonym": synonym})
            if len(hits) >= max_items:
                return hits
    return hits


def list_assignment_sources() -> list[dict[str, str]]:
    return [
        {
            "id": "docflow_protocol",
            "title": "Документооборот: задачи протоколов (ТД_ЗадачиПротоколов)",
        },
        {
            "id": "docflow_orders",
            "title": "Документооборот: поручения (ТД) — Document.ТД_Поручения",
        },
        {
            "id": "erp_performer_tasks",
            "title": "ERP: Задача.ЗадачаИсполнителя",
        },
        {
            "id": "crm_user_tasks",
            "title": "CRM: регистр CRM_ЗадачиПользователей",
        },
        {
            "id": "business_process_assignment",
            "title": "Бизнес-процесс: Задание",
        },
    ]


def _normalize_work_item(row: dict[str, Any], *, default_source: str) -> dict[str, Any]:
    title = str(
        row.get("title")
        or row.get("description")
        or row.get("task")
        or row.get("Задача")
        or ""
    ).strip()
    due = _normalize_due_value(
        str(row.get("due_at") or row.get("due_date") or row.get("СрокИсполнения") or "")
    )
    return {
        "number": str(row.get("number") or row.get("doc_number") or ""),
        "title": title,
        "description": title,
        "date": str(row.get("date") or row.get("created_at") or "")[:19],
        "due_date": due,
        "due_at": due,
        "executor": str(row.get("executor") or row.get("performer") or ""),
        "performer": str(row.get("performer") or row.get("executor") or ""),
        "author": str(row.get("author") or ""),
        "meeting_topic": str(row.get("meeting_topic") or ""),
        "about": str(row.get("about") or ""),
        "priority": str(row.get("priority") or ""),
        "status": str(row.get("status") or "открыта"),
        "source": str(row.get("source") or default_source),
    }


def _normalize_due_value(raw: str) -> str:
    text = (raw or "").strip()
    if not text or text.startswith("0100-") or text.startswith("0001-01-01"):
        return ""
    return text.replace("T", " ")[:19]


def query_work_items(
    app: Any,
    *,
    user_name: str = "",
    scope: str = "all",
    limit: int = 100,
    only_open: bool = True,
) -> dict[str, Any]:
    """Aggregate work items from multiple 1C sources (not only ЗадачаИсполнителя)."""
    actor = (user_name or get_current_user_name(app)).strip()
    safe_name = actor.replace('"', '""')
    scope_key = (scope or "all").strip().casefold()
    scopes = {
        "docflow",
        "docflow_protocol",
        "docflow_orders",
        "erp_tasks",
        "crm",
        "business_process",
        "all",
    }
    if scope_key not in scopes:
        raise ValueError(f"Unknown scope: {scope}. Allowed: {', '.join(sorted(scopes))}")

    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    sources_used: list[str] = []
    per_source = max(1, min(int(limit or 100), 200))

    def _add_rows(rows: list[dict[str, Any]], source_id: str) -> None:
        if not rows:
            return
        sources_used.append(source_id)
        for row in rows:
            item = _normalize_work_item(row, default_source=source_id)
            if not item.get("title"):
                continue
            key = f"{source_id}:{item.get('number')}:{item['title'][:80]}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)

    if scope_key in {"all", "docflow", "docflow_protocol"}:
        _add_rows(
            _fetch_docflow_protocol_rows(app, safe_name=safe_name, limit=per_source, only_open=only_open),
            "td_задачи_протоколов",
        )
    if scope_key in {"all", "docflow", "docflow_orders"}:
        _add_rows(
            _fetch_docflow_orders_rows(app, safe_name=safe_name, limit=per_source, only_open=only_open),
            "td_поручения",
        )
    if scope_key in {"all", "erp_tasks"}:
        erp_rows, erp_source = query_performer_tasks(
            app, mine_only=True, limit=per_source, prefer_crm=False
        )
        _add_rows(erp_rows, erp_source)
    if scope_key in {"all", "crm"}:
        _add_rows(query_crm_my_tasks(app, user_name=actor, limit=per_source), "crm_мои_задачи")
    if scope_key in {"all", "business_process"}:
        _add_rows(
            _fetch_business_process_rows(app, safe_name=safe_name, limit=per_source, only_open=only_open),
            "bp_задание",
        )

    return {
        "fio": actor,
        "scope": scope_key,
        "only_open": only_open,
        "count": len(merged[:per_source]),
        "tasks": merged[:per_source],
        "sources": sources_used,
        "available_sources": list_assignment_sources(),
    }


def _fetch_docflow_protocol_rows(
    app: Any, *, safe_name: str, limit: int, only_open: bool
) -> list[dict[str, Any]]:
    open_filter = "И НЕ Р.Выполнена" if only_open else ""
    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ {limit}
        Р.НомерПунктаПротокола КАК ItemNumber,
        Р.Задача КАК Description,
        Р.СрокИсполнения КАК DueDate,
        Р.ДатаПостановкиЗадачи КАК Date,
        Р.Ответственный.Наименование КАК Executor,
        Р.Автор.Наименование КАК Author,
        Р.ТемаСовещания.Наименование КАК MeetingTopic,
        Р.Выполнена КАК Done
        ИЗ РегистрСведений.ТД_ЗадачиПротоколов КАК Р
        ГДЕ Р.Ответственный.Наименование = "{safe_name}"
            {open_filter}
        УПОРЯДОЧИТЬ ПО Р.СрокИсполнения, Р.ДатаПостановкиЗадачи УБЫВ"""
    try:
        table = app.NewObject("Query", query_text).Execute().Unload()
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for i in range(table.Count()):
        row = table.Get(i)
        title = _row_field(row, "Description")
        if not title:
            continue
        item_no = _row_field(row, "ItemNumber")
        rows.append(
            {
                "number": f"ТД-п.{item_no}" if item_no else "",
                "description": title,
                "title": title,
                "date": _row_field(row, "Date"),
                "due_date": _row_field(row, "DueDate"),
                "executor": _row_field(row, "Executor"),
                "author": _row_field(row, "Author"),
                "meeting_topic": _row_field(row, "MeetingTopic"),
                "status": "выполнена"
                if str(_row_field(row, "Done")).lower() in {"true", "истина", "1", "да"}
                else "открыта",
            }
        )
    return rows


def _fetch_docflow_orders_rows(
    app: Any, *, safe_name: str, limit: int, only_open: bool
) -> list[dict[str, Any]]:
    _ = only_open
    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ {limit}
        Д.Номер КАК DocNumber,
        Д.Дата КАК DocDate,
        Д.ОЧем КАК About,
        Стр.Мероприятие КАК Description,
        Стр.СрокИсполнения КАК DueDate,
        Стр.ОтветственноеЛицо.Наименование КАК Executor,
        Стр.Приоритет КАК Priority
        ИЗ Документ.ТД_Поручения.Поручения КАК Стр
        ЛЕВОЕ СОЕДИНЕНИЕ Документ.ТД_Поручения КАК Д
            ПО Стр.Ссылка = Д.Ссылка
        ГДЕ НЕ Д.ПометкаУдаления
            И Стр.ОтветственноеЛицо.Наименование = "{safe_name}"
        УПОРЯДОЧИТЬ ПО Стр.СрокИсполнения УБЫВ, Д.Дата УБЫВ"""
    try:
        table = app.NewObject("Query", query_text).Execute().Unload()
    except Exception:
        return []
    rows: list[dict[str, Any]] = []
    for i in range(table.Count()):
        row = table.Get(i)
        title = _row_field(row, "Description")
        if not title:
            continue
        rows.append(
            {
                "number": _row_field(row, "DocNumber"),
                "description": title,
                "title": title,
                "date": _row_field(row, "DocDate"),
                "due_date": _row_field(row, "DueDate"),
                "executor": _row_field(row, "Executor"),
                "about": _row_field(row, "About"),
                "priority": _row_field(row, "Priority"),
                "status": "открыта",
            }
        )
    return rows


def _fetch_business_process_rows(
    app: Any, *, safe_name: str, limit: int, only_open: bool
) -> list[dict[str, Any]]:
    open_filter = "И НЕ Б.Завершен" if only_open else ""
    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ {limit}
        Б.Номер КАК Number,
        Б.Наименование КАК Description,
        Б.Дата КАК Date,
        Б.СрокИсполнения КАК DueDate,
        Б.Исполнитель.Наименование КАК Executor,
        Б.Автор.Наименование КАК Author
        ИЗ БизнесПроцесс.Задание КАК Б
        ГДЕ Б.Стартован
            {open_filter}
            И Б.Исполнитель.Наименование = "{safe_name}"
        УПОРЯДОЧИТЬ ПО Б.Дата УБЫВ"""
    try:
        table = app.NewObject("Query", query_text).Execute().Unload()
    except Exception:
        return []
    return _rows_from_table(table, source="bp_задание")


def query_docflow_assignments(
    app: Any,
    *,
    user_name: str = "",
    limit: int = 100,
    only_open: bool = True,
) -> list[dict[str, Any]]:
    """Поручения (ТД) — регистр ТД_ЗадачиПротоколов + табличная часть Document.ТД_Поручения."""
    payload = query_work_items(
        app,
        user_name=user_name,
        scope="docflow",
        limit=limit,
        only_open=only_open,
    )
    return list(payload.get("tasks") or [])


def query_crm_my_tasks(app: Any, *, user_name: str, limit: int = 30) -> list[dict[str, Any]]:
    """CRM «Мои задачи» — register CRM_ЗадачиПользователей (start page widget)."""
    limit = max(1, min(100, int(limit)))
    safe_name = user_name.replace('"', '""')
    query_text = f"""ВЫБРАТЬ ПЕРВЫЕ {limit}
        Р.Номер КАК Number,
        Р.Наименование КАК Description,
        Р.Поставлено КАК Date,
        Р.КрайнийСрок КАК DueDate,
        Р.Пользователь.Наименование КАК Executor
        ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
        ГДЕ Р.Пользователь.Наименование = "{safe_name}"
            И Р.Закрыта = ДАТАВРЕМЯ(1, 1, 1)
        УПОРЯДОЧИТЬ ПО Р.Поставлено УБЫВ"""
    table = app.NewObject("Query", query_text).Execute().Unload()
    return _rows_from_table(table, source="crm_мои_задачи")


def query_performer_tasks(
    app: Any,
    *,
    mine_only: bool = True,
    limit: int = 30,
    prefer_crm: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    limit = max(1, min(100, int(limit)))
    user_name = get_current_user_name(app) if mine_only else ""

    if mine_only and user_name:
        query_text = f"""ВЫБРАТЬ ПЕРВЫЕ {limit}
            Т.Номер КАК Number,
            Т.Наименование КАК Description,
            Т.Дата КАК Date,
            Т.СрокИсполнения КАК DueDate,
            Т.Исполнитель.Наименование КАК Executor
            ИЗ Задача.ЗадачаИсполнителя КАК Т
            ГДЕ НЕ Т.Выполнена
                И Т.Исполнитель.Наименование = "{user_name.replace('"', '""')}"
            УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
        table = app.NewObject("Query", query_text).Execute().Unload()
        erp_rows = _rows_from_table(table, source="erp_задача_исполнителя")
        if erp_rows or not prefer_crm:
            return erp_rows, "erp_задача_исполнителя"

    if prefer_crm and mine_only and user_name:
        crm_rows = query_crm_my_tasks(app, user_name=user_name, limit=limit)
        if crm_rows:
            return crm_rows, "crm_мои_задачи"

    if not mine_only:
        query_text = f"""ВЫБРАТЬ ПЕРВЫЕ {limit}
            Т.Номер КАК Number,
            Т.Наименование КАК Description,
            Т.Дата КАК Date,
            Т.СрокИсполнения КАК DueDate,
            Т.Исполнитель.Наименование КАК Executor
            ИЗ Задача.ЗадачаИсполнителя КАК Т
            ГДЕ НЕ Т.Выполнена
            УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
        table = app.NewObject("Query", query_text).Execute().Unload()
        return _rows_from_table(table, source="erp_задача_исполнителя_all"), "erp_задача_исполнителя_all"

    return [], "erp_задача_исполнителя"


def connect_application(*, progid: str = "", connection_string: str = "") -> tuple[Any, str, str]:
    import win32com.client

    conn = connection_string or build_connection_string()
    if not conn.strip():
        raise RuntimeError(
            "ONEC_COM_CONNECTION_REQUIRED: set ONEC_COM_SERVER/ONEC_COM_REF or ERP_LOGIN/ERP_PASSWORD in infra/.env"
        )

    last_exc: Exception | None = None

    for candidate in _APPLICATION_PROGIDS:
        try:
            obj = win32com.client.GetActiveObject(candidate)
            return obj, "active", candidate
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    connector_progids = [progid] if progid else []
    default = _strip_env_value(os.environ.get("ONEC_COM_PROGID") or "V83.COMConnector")
    connector_progids.extend([default, *_COM_CONNECTOR_PROGIDS])

    seen: set[str] = set()
    ordered: list[str] = []
    for item in connector_progids:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)

    for candidate in ordered:
        try:
            connector = win32com.client.Dispatch(candidate)
            app = connector.Connect(conn)
            return app, "connected", candidate
        except Exception as exc:  # noqa: BLE001
            last_exc = exc

    raise RuntimeError(
        f"ONEC_COM_UNAVAILABLE: cannot connect to 1C ERP via COM ({last_exc}). "
        "Register comcntr.dll (regsvr32) and set ONEC_COM_SERVER to ragent host without HTTP port."
    ) from last_exc


def connect_session(*, progid: str = "") -> dict[str, Any]:
    require_32bit_python()
    obj, mode, used_progid = connect_application(progid=progid)
    session_id = str(uuid.uuid4())
    current_user = ""
    try:
        current_user = get_current_user_name(obj)
    except Exception:
        pass
    return {
        "session_id": session_id,
        "object": obj,
        "progid": used_progid,
        "mode": mode,
        "connection": build_connection_string(),
        "current_user": current_user,
        "python_bitness": python_bitness(),
    }


def service_status() -> dict[str, Any]:
    conn = build_connection_string()
    server, ref = _server_ref_from_env()
    status: dict[str, Any] = {
        "python_bitness": python_bitness(),
        "ready": python_bitness() == 32,
        "connection_configured": bool(conn.strip()),
        "progid": os.environ.get("ONEC_COM_PROGID") or "V83.COMConnector",
        "com_server": _strip_env_value(os.environ.get("ONEC_COM_SERVER") or "") or server,
        "com_ref": _strip_env_value(os.environ.get("ONEC_COM_REF") or "") or ref,
        "transport": "com-connector",
    }
    if python_bitness() != 32:
        status["error"] = "Service must run under 32-bit Python (py -3.12-32)"
    return status
