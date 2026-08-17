"""Server-side 1C OData / SQL tools (ported from jalko platform-tool-onec).

Runs in-process inside the Constructor backend. Desktop must not execute onec.*.
When ODATA_BASE_URL + credentials are set → real OData; otherwise → stub.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.services.erp_tasks import (
    ErpTaskError,
    handle_current as _erp_tasks_current,
    handle_period as _erp_tasks_period,
    handle_subordinate_tasks as _erp_subordinate_tasks,
    stub_current as _stub_erp_tasks_current,
    stub_period as _stub_erp_tasks_period,
    stub_subordinate_tasks as _stub_erp_subordinate_tasks,
)
from app.services.onec_security import (
    default_odata_entities,
    looks_like_odata_entity,
    odata_entity_allowlist,
    sql_table_allowlist,
    stub_odata_rows,
    validate_odata_entity,
    validate_odata_path,
    validate_sql_query,
)

_INCOMING_DOC_MARKERS = (
    "Document_ТД_ВходящаяКорреспонденция",
    "Document_ВходящаяКорреспонденция",
)
_TOP_RE = re.compile(r"\$top=(\d+)", re.IGNORECASE)
_SKIP_RE = re.compile(r"\$skip=(\d+)", re.IGNORECASE)
_ENTITYSET_NAME_RE = re.compile(r"<EntitySet\b[^>]*\bName=\"([^\"]+)\"", re.IGNORECASE)
_COLLECTION_HREF_RE = re.compile(r"<collection\b[^>]*\bhref=\"([^\"]+)\"", re.IGNORECASE)
_KIND_ALIASES = {
    "document": "document",
    "documents": "document",
    "документ": "document",
    "документы": "document",
    "catalog": "catalog",
    "catalogs": "catalog",
    "table": "catalog",
    "tables": "catalog",
    "таблица": "catalog",
    "таблицы": "catalog",
    "справочник": "catalog",
    "справочники": "catalog",
    "register": "register",
    "registers": "register",
    "регистр": "register",
    "регистры": "register",
    "other": "other",
    "прочее": "other",
}
_REGISTER_PREFIXES = (
    "InformationRegister_",
    "AccumulationRegister_",
    "AccountingRegister_",
    "CalculationRegister_",
)
_stub_counter = 0
_catalog_cache: list[dict[str, str]] | None = None

ONEC_TOOLS = frozenset(
    {
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.odata_post",
        "onec.odata_patch",
        "onec.attach_file",
        "onec.sql_query",
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
    }
)
_ERP_TASK_TOOLS = frozenset(
    {
        "onec.erp_tasks_current",
        "onec.erp_tasks_period",
        "onec.erp_subordinate_tasks",
    }
)


class OnecToolError(RuntimeError):
    pass


def odata_configured() -> bool:
    has_url = bool(settings.odata_base_url.strip())
    has_creds = bool(
        (settings.erp_login.strip() and settings.erp_password.strip())
        or (settings.odata_username.strip() and settings.odata_password.strip())
    )
    return has_url and has_creds


def _erp_sql_ready() -> bool:
    return bool(
        settings.erp_sql_server
        and (
            settings.erp_sql_trusted_connection
            or (settings.erp_sql_user and settings.erp_sql_password)
        )
    )


def invoke_onec(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    actor_user_id: str = "",
    actor_fio: str = "",
) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    handlers = REAL_HANDLERS if odata_configured() else STUB_HANDLERS
    # sql_query / задачи работают от ERP SQL даже без OData URL
    if _erp_sql_ready() and not odata_configured():
        extra = {"onec.sql_query": _sql_query}
        extra.update({name: REAL_HANDLERS[name] for name in _ERP_TASK_TOOLS})
        handlers = {**STUB_HANDLERS, **extra}
    elif _erp_sql_ready():
        handlers = {**handlers, **{name: REAL_HANDLERS[name] for name in _ERP_TASK_TOOLS}}
    handler = handlers.get(tool)
    if handler is None:
        raise OnecToolError(f"Неизвестный 1С-инструмент: {tool}")
    try:
        if tool in _ERP_TASK_TOOLS:
            return handler(args, actor_fio=actor_fio, actor_user_id=actor_user_id)
        return handler(args)
    except OnecToolError:
        raise
    except ErpTaskError as exc:
        raise OnecToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise OnecToolError(str(exc)) from exc


def _next_stub_id() -> int:
    global _stub_counter
    _stub_counter += 1
    return _stub_counter


def _is_incoming_correspondence_path(path: str) -> bool:
    return any(marker in path for marker in _INCOMING_DOC_MARKERS)


def _parse_top_limit(path: str, payload: dict[str, Any]) -> int:
    match = _TOP_RE.search(path)
    if match:
        return max(1, min(100, int(match.group(1))))
    raw_top = payload.get("top")
    if raw_top is not None:
        return max(1, min(100, int(raw_top)))
    return 3


def _parse_skip(path: str, payload: dict[str, Any]) -> int:
    """OData $skip — смещение (сколько записей пропустить)."""
    match = _SKIP_RE.search(path or "")
    if match:
        return max(0, min(100_000, int(match.group(1))))
    raw_skip = payload.get("skip")
    if raw_skip is not None:
        return max(0, min(100_000, int(raw_skip)))
    return 0


def _entity_from_args(args: dict[str, Any]) -> str:
    entity = str(args.get("entity", "")).strip()
    if entity:
        return entity.lstrip("/")
    path = str(args.get("path", "")).strip().lstrip("/")
    if not path:
        return ""
    head = path.split("?", 1)[0]
    if _is_incoming_correspondence_path(head):
        return (
            settings.odata_incoming_doc_entity
            or "Document_ТД_ВходящаяКорреспонденция"
        ).strip()
    return head


def _looks_like_odata_entity(entity: str) -> bool:
    return looks_like_odata_entity(entity)


def _odata_allowlist() -> set[str] | None:
    return odata_entity_allowlist(settings.onec_odata_entity_allowlist)


def _odata_extra_entities(*, autoload: bool = True) -> set[str]:
    return set(_cached_catalog_names(autoload=autoload))


def _sql_allowlist() -> set[str]:
    return sql_table_allowlist(settings.onec_sql_allowlist)


def _build_list_path(entity: str, top: int, *, skip: int = 0) -> str:
    entity = entity.strip().lstrip("/")
    path = f"{entity}?$format=json&$top={top}"
    if skip > 0:
        path = f"{path}&$skip={skip}"
    return path


def _ensure_odata_query(
    path: str,
    *,
    top: int | None = None,
    skip: int | None = None,
) -> str:
    """1C OData: $format=json; пагинация через $top (лимит) и $skip (смещение)."""
    normalized = path.strip().lstrip("/")
    if "$format" not in normalized.lower():
        normalized = f"{normalized}{'&' if '?' in normalized else '?'}$format=json"
    if top is not None and "$top" not in normalized.lower():
        normalized = f"{normalized}&$top={top}"
    if skip is not None and skip > 0 and "$skip" not in normalized.lower():
        normalized = f"{normalized}&$skip={skip}"
    return normalized


def _payload_credentials(payload: dict[str, Any]) -> tuple[str, str] | None:
    username = str(
        payload.get("username") or payload.get("erp_login") or payload.get("user") or ""
    ).strip()
    password = str(payload.get("password") or payload.get("erp_password") or "").strip()
    if username and password:
        return username, password
    return None


def _odata_auth(args: dict[str, Any] | None = None) -> tuple[str, str] | None:
    payload = args or {}
    explicit = _payload_credentials(payload)
    if explicit:
        return explicit
    if settings.erp_login and settings.erp_password:
        return settings.erp_login, settings.erp_password
    if settings.odata_username and settings.odata_password:
        return settings.odata_username, settings.odata_password
    return None


def _parse_onec_http_error(response: httpx.Response) -> str:
    text = response.text.lstrip("\ufeff")
    try:
        data = json.loads(text)
        exc = data.get("exception")
        if isinstance(exc, dict):
            desc = str(exc.get("descr") or exc.get("desc") or "").strip()
            if desc:
                if response.status_code == 402:
                    return f"1C OData: неверный пользователь или пароль (HTTP 402). {desc}"
                return f"1C OData HTTP {response.status_code}: {desc}"
    except json.JSONDecodeError:
        pass
    if response.status_code == 402:
        return (
            "1C OData: неверный пользователь или пароль (HTTP 402). "
            "Укажите ERP_LOGIN/ERP_PASSWORD или ODATA_USERNAME/ODATA_PASSWORD в backend/.env."
        )
    return f"1C OData HTTP {response.status_code}: {text[:300]}"


def _normalize_odata_rows(data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    rows = data.get("value")
    if not isinstance(rows, list):
        return []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append(
            {
                "Ref_Key": row.get("Ref_Key"),
                "Number": row.get("Number") or row.get("Code"),
                "Date": row.get("Date") or row.get("Дата"),
                "Description": row.get("Description")
                or row.get("Комментарий")
                or row.get("Наименование")
                or row.get("Description"),
                "Subject": row.get("Тема") or row.get("Subject"),
                "Posted": row.get("Posted"),
            }
        )
    return normalized


def _fetch_odata_list(args: dict[str, Any]) -> dict[str, Any]:
    path = str(args.get("path", "")).strip()
    entity = _entity_from_args(args)
    if not entity:
        raise OnecToolError("entity or path required")
    entity = validate_odata_entity(
        entity,
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    top = _parse_top_limit(path, args)
    skip = _parse_skip(path, args)
    cleaned_path = path.strip().lstrip("/")
    if cleaned_path and cleaned_path.split("?", 1)[0] == entity:
        odata_path = _ensure_odata_query(cleaned_path, top=top, skip=skip)
    else:
        odata_path = _build_list_path(entity, top, skip=skip)
    if not settings.odata_base_url:
        raise OnecToolError(
            "ODATA_BASE_URL не настроен. Добавьте ODATA_BASE_URL, "
            "ODATA_USERNAME/ODATA_PASSWORD (или ERP_LOGIN/ERP_PASSWORD) в backend/.env."
        )

    raw = _odata_get({"path": odata_path, **{k: v for k, v in args.items() if k != "path"}})
    payload = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    value = _normalize_odata_rows(payload)
    numbers = [str(item.get("Number") or "") for item in value if item.get("Number")]
    summary = f"получено {len(value)} записей из 1С OData ({entity})"
    if numbers:
        summary += f": {', '.join(numbers)}"
    return {
        "summary": summary,
        "path": odata_path,
        "entity": entity,
        "count": len(value),
        "top": top,
        "skip": skip,
        "value": value,
        "source": "odata",
    }


def _odata_get_dispatch(args: dict[str, Any]) -> dict[str, Any]:
    entity = _entity_from_args(args)
    path = str(args.get("path", ""))
    if (
        _is_incoming_correspondence_path(path)
        or _looks_like_odata_entity(entity)
        or entity in _odata_extra_entities()
    ):
        return _fetch_odata_list(args)
    return _odata_get(args)


def _stub_odata_get(args: dict[str, Any]) -> dict[str, Any]:
    entity = _entity_from_args(args)
    path = str(args.get("path", ""))
    if (
        _is_incoming_correspondence_path(path)
        or _looks_like_odata_entity(entity)
        or entity in _odata_extra_entities()
    ):
        if not entity:
            raise OnecToolError("entity or path required")
        entity = validate_odata_entity(
            entity,
            allowlist=_odata_allowlist(),
            extra_allowed=_odata_extra_entities(),
        )
        top = _parse_top_limit(path, args)
        return stub_odata_rows(entity, top)
    path_clean = path.strip().lstrip("/")
    if path_clean:
        validate_odata_path(
            path_clean,
            allowlist=_odata_allowlist(),
            extra_allowed=_odata_extra_entities(),
        )
    return {
        "summary": "stub odata get",
        "path": path,
        "value": [{"Ref_Key": "00000000-0000-0000-0000-000000000001"}],
        "source": "stub",
    }


def _stub_odata_post(args: dict[str, Any]) -> dict[str, Any]:
    n = _next_stub_id()
    return {
        "summary": f"stub document {n}",
        "erp_document_number": f"ВК-STUB-{n:06d}",
        "erp_document_id": f"11111111-1111-1111-1111-{n:012d}"[:36],
        "source": "stub",
    }


def _stub_odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "stub patch ok",
        "updated": True,
        "ref_key": args.get("ref_key"),
        "source": "stub",
    }


def _stub_attach_file(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": "stub attach",
        "ref_key": args.get("document_ref_key"),
        "filename": args.get("filename", "file.pdf"),
        "source": "stub",
    }


def _stub_sql_query(args: dict[str, Any]) -> dict[str, Any]:
    sql = validate_sql_query(str(args.get("sql", "")), allowlist=_sql_allowlist())
    return {
        "summary": "stub sql",
        "sql": sql,
        "rows": [{"id": 1, "name": "stub"}],
        "source": "stub",
    }


def _odata_url(path: str) -> str:
    from urllib.parse import quote

    base = settings.odata_base_url.rstrip("/")
    cleaned = path.lstrip("/")
    safe = "/()'=,:$"
    if "?" in cleaned:
        head, query = cleaned.split("?", 1)
        return f"{base}/{quote(head, safe=safe)}?{query}"
    return f"{base}/{quote(cleaned, safe=safe)}"


def _odata_get(args: dict[str, Any]) -> dict[str, Any]:
    raw_path = str(args.get("path", ""))
    path = validate_odata_path(
        raw_path,
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    top = _parse_top_limit(raw_path, args) if raw_path else None
    skip = _parse_skip(raw_path, args) if raw_path else None
    path = _ensure_odata_query(
        path,
        top=top if top is not None and "$top" not in path.lower() else None,
        skip=skip if skip and "$skip" not in path.lower() else None,
    )
    if not settings.odata_base_url:
        raise OnecToolError("ODATA_BASE_URL not configured")
    auth = _odata_auth(args)
    if not auth:
        raise OnecToolError(
            "OData credentials not configured: set ERP_LOGIN/ERP_PASSWORD "
            "или ODATA_USERNAME/ODATA_PASSWORD"
        )
    url = _odata_url(path)
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise OnecToolError(_parse_onec_http_error(response))
        data = response.json()
    return {"summary": "odata get ok", "path": path, "data": data, "source": "odata"}


def _odata_post(args: dict[str, Any]) -> dict[str, Any]:
    entity = validate_odata_entity(
        str(args.get("entity", "")),
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    body = args.get("body") or {}
    if not settings.odata_base_url:
        raise OnecToolError("ODATA_BASE_URL not configured")
    auth = _odata_auth(args)
    if not auth:
        raise OnecToolError("OData credentials not configured")
    url = _odata_url(entity)
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.post(url, json=body, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise OnecToolError(_parse_onec_http_error(response))
        data = response.json()
    return {
        "summary": "odata post ok",
        "erp_document_id": data.get("Ref_Key") or data.get("ref_key"),
        "data": data,
        "source": "odata",
    }


def _odata_patch(args: dict[str, Any]) -> dict[str, Any]:
    entity = validate_odata_entity(
        str(args.get("entity", "")),
        allowlist=_odata_allowlist(),
        extra_allowed=_odata_extra_entities(),
    )
    ref_key = str(args.get("ref_key", "")).strip()
    body = args.get("body") or {}
    if not ref_key:
        raise OnecToolError("ref_key required")
    url = _odata_url(f"{entity}(guid'{ref_key}')")
    auth = _odata_auth(args)
    if not auth:
        raise OnecToolError("OData credentials not configured")
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.patch(url, json=body, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise OnecToolError(_parse_onec_http_error(response))
    return {"summary": "odata patch ok", "updated": True, "ref_key": ref_key, "source": "odata"}


def _attach_file(_args: dict[str, Any]) -> dict[str, Any]:
    raise OnecToolError(
        "NOT_IMPLEMENTED: onec.attach_file требует OData file upload — пока недоступно. "
        "Используйте onec.odata_patch для метаданных или прикрепите файл вручную в 1С."
    )


def _build_connection_string() -> str:
    parts = [
        f"DRIVER={{{settings.erp_sql_driver}}}",
        f"SERVER={settings.erp_sql_server}",
        f"DATABASE={settings.erp_sql_database}",
        f"Encrypt={settings.erp_sql_encrypt}",
        "TrustServerCertificate=yes",
    ]
    if settings.erp_sql_trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={settings.erp_sql_user}")
        parts.append(f"PWD={settings.erp_sql_password}")
    return ";".join(parts) + ";"


def _sql_query(args: dict[str, Any]) -> dict[str, Any]:
    try:
        import pyodbc
    except ImportError as exc:
        raise OnecToolError("pyodbc не установлен") from exc
    sql = validate_sql_query(str(args.get("sql", "")), allowlist=_sql_allowlist())
    conn = pyodbc.connect(_build_connection_string(), autocommit=True)
    try:
        cur = conn.cursor()
        cur.execute(sql)
        columns = [col[0] for col in cur.description] if cur.description else []
        rows = []
        for row in cur.fetchmany(100):
            rows.append({columns[i]: row[i] for i in range(len(columns))})
    finally:
        conn.close()
    return {"summary": f"rows={len(rows)}", "rows": rows, "source": "sql"}


def _classify_odata_entity(name: str) -> str:
    if name.startswith("Document_"):
        return "document"
    if name.startswith("Catalog_"):
        return "catalog"
    if name.startswith(_REGISTER_PREFIXES):
        return "register"
    return "other"


def _entity_prefix(name: str) -> str:
    for prefix in (
        "InformationRegister_",
        "AccumulationRegister_",
        "AccountingRegister_",
        "CalculationRegister_",
        "ChartOfCharacteristicTypes_",
        "ChartOfAccounts_",
        "ChartOfCalculationTypes_",
        "BusinessProcess_",
        "ExchangePlan_",
        "Document_",
        "Catalog_",
        "Constant_",
        "Task_",
        "Enum_",
    ):
        if name.startswith(prefix):
            return prefix.rstrip("_")
    return ""


def _catalog_item(name: str) -> dict[str, str] | None:
    cleaned = str(name or "").strip().lstrip("/").split("?", 1)[0]
    cleaned = cleaned.split("(", 1)[0]
    if "/" in cleaned:
        cleaned = cleaned.rsplit("/", 1)[-1]
    if not cleaned or cleaned.startswith("$"):
        return None
    return {
        "name": cleaned,
        "kind": _classify_odata_entity(cleaned),
        "prefix": _entity_prefix(cleaned),
    }


def _stub_catalog_items() -> list[dict[str, str]]:
    names = list(default_odata_entities()) + [
        "Catalog_Контрагенты",
        "AccumulationRegister_Остатки",
        "InformationRegister_КурсыВалют",
    ]
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in names:
        item = _catalog_item(name)
        if item is None or item["name"] in seen:
            continue
        seen.add(item["name"])
        items.append(item)
    return items


def _names_from_service_document(data: Any) -> list[str]:
    names: list[str] = []
    if not isinstance(data, dict):
        return names
    value = data.get("value")
    if not isinstance(value, list):
        return names
    for item in value:
        if isinstance(item, dict):
            raw = str(item.get("name") or item.get("url") or "").strip()
        elif isinstance(item, str):
            raw = item.strip()
        else:
            continue
        if raw:
            names.append(raw)
    return names


def _names_from_metadata_xml(text: str) -> list[str]:
    names = [match.group(1) for match in _ENTITYSET_NAME_RE.finditer(text)]
    if names:
        return names
    return [match.group(1) for match in _COLLECTION_HREF_RE.finditer(text)]


def _items_from_names(names: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in names:
        item = _catalog_item(name)
        if item is None or item["name"] in seen:
            continue
        seen.add(item["name"])
        items.append(item)
    items.sort(key=lambda row: (row["kind"], row["name"]))
    return items


def _cached_catalog_names(*, autoload: bool = True) -> set[str]:
    global _catalog_cache
    if _catalog_cache is None and autoload:
        try:
            if odata_configured():
                _load_odata_catalog()
            else:
                _catalog_cache = _stub_catalog_items()
        except Exception:  # noqa: BLE001
            return set()
    if not _catalog_cache:
        return set()
    return {item["name"] for item in _catalog_cache}


def _load_odata_catalog(*, force: bool = False) -> list[dict[str, str]]:
    global _catalog_cache
    if _catalog_cache is not None and not force:
        return _catalog_cache
    if not settings.odata_base_url:
        raise OnecToolError("ODATA_BASE_URL not configured")
    auth = _odata_auth()
    if not auth:
        raise OnecToolError(
            "OData credentials not configured: set ERP_LOGIN/ERP_PASSWORD "
            "или ODATA_USERNAME/ODATA_PASSWORD"
        )
    names: list[str] = []
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        service_url = settings.odata_base_url.rstrip("/")
        response = client.get(
            service_url,
            params={"$format": "json"},
            headers={"Accept": "application/json"},
        )
        if response.status_code < 400:
            try:
                names = _names_from_service_document(response.json())
            except json.JSONDecodeError:
                names = []
        if not names:
            meta = client.get(
                _odata_url("$metadata"),
                headers={"Accept": "application/xml"},
            )
            if meta.status_code >= 400:
                raise OnecToolError(_parse_onec_http_error(meta))
            names = _names_from_metadata_xml(meta.text)
    if not names:
        raise OnecToolError("1C OData: пустой каталог сущностей (service document / $metadata)")
    _catalog_cache = _items_from_names(names)
    return _catalog_cache


def _normalize_kind_filter(raw: str) -> str:
    return _KIND_ALIASES.get(raw.strip().casefold(), "")


def _format_catalog(
    items: list[dict[str, str]],
    args: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    kind = _normalize_kind_filter(str(args.get("kind") or args.get("type") or ""))
    search = str(args.get("search") or args.get("query") or "").strip().casefold()
    try:
        limit = int(args.get("limit") or 400)
    except (TypeError, ValueError):
        limit = 400
    limit = max(1, min(2000, limit))

    filtered = items
    if kind:
        filtered = [item for item in filtered if item["kind"] == kind]
    if search:
        filtered = [item for item in filtered if search in item["name"].casefold()]
    truncated = filtered[:limit]

    documents = [item["name"] for item in truncated if item["kind"] == "document"]
    catalogs = [item["name"] for item in truncated if item["kind"] == "catalog"]
    registers = [item["name"] for item in truncated if item["kind"] == "register"]
    other = [item["name"] for item in truncated if item["kind"] == "other"]
    summary = (
        f"OData каталог: {len(documents)} документов, "
        f"{len(catalogs)} справочников/таблиц, {len(registers)} регистров"
    )
    if other and not kind:
        summary += f", {len(other)} прочих"
    if search or kind:
        summary += f" (показано {len(truncated)} из {len(filtered)})"
    return {
        "summary": summary,
        "source": source,
        "count": len(truncated),
        "total_matched": len(filtered),
        "kind": kind or "all",
        "search": search,
        "documents": documents,
        "catalogs": catalogs,
        "registers": registers,
        "other": other,
        "entities": truncated,
    }


def _odata_catalog(args: dict[str, Any]) -> dict[str, Any]:
    force = bool(args.get("refresh") or args.get("force"))
    items = _load_odata_catalog(force=force)
    return _format_catalog(items, args, source="odata")


def _stub_odata_catalog(args: dict[str, Any]) -> dict[str, Any]:
    global _catalog_cache
    items = _stub_catalog_items()
    if _catalog_cache is None:
        _catalog_cache = items
    return _format_catalog(items, args, source="stub")


STUB_HANDLERS = {
    "onec.odata_catalog": _stub_odata_catalog,
    "onec.odata_get": _stub_odata_get,
    "onec.odata_post": _stub_odata_post,
    "onec.odata_patch": _stub_odata_patch,
    "onec.attach_file": _stub_attach_file,
    "onec.sql_query": _stub_sql_query,
    "onec.erp_tasks_current": _stub_erp_tasks_current,
    "onec.erp_tasks_period": _stub_erp_tasks_period,
    "onec.erp_subordinate_tasks": _stub_erp_subordinate_tasks,
}

REAL_HANDLERS = {
    "onec.odata_catalog": _odata_catalog,
    "onec.odata_get": _odata_get_dispatch,
    "onec.odata_post": _odata_post,
    "onec.odata_patch": _odata_patch,
    "onec.attach_file": _attach_file,
    "onec.sql_query": _sql_query,
    "onec.erp_tasks_current": _erp_tasks_current,
    "onec.erp_tasks_period": _erp_tasks_period,
    "onec.erp_subordinate_tasks": _erp_subordinate_tasks,
}
