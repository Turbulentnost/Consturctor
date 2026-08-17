from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
import pyodbc
from pydantic import Field
from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app
from platform_tool_onec.security import (
    odata_entity_allowlist,
    sql_table_allowlist,
    stub_odata_rows,
    validate_odata_entity,
    validate_odata_path,
    validate_sql_query,
)


class OnecSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-onec"
    api_port: int = 7822
    odata_base_url: str = ""
    odata_username: str = ""
    odata_password: str = ""
    odata_timeout_sec: float = 60.0
    odata_incoming_doc_entity: str = "Document_ТД_ВходящаяКорреспонденция"
    erp_login: str = Field(default="", validation_alias="ERP_LOGIN")
    erp_password: str = Field(default="", validation_alias="ERP_PASSWORD")
    erp_sql_server: str = "ii1"
    erp_sql_database: str = "erp_pm"
    erp_sql_driver: str = "ODBC Driver 18 for SQL Server"
    erp_sql_trusted_connection: bool = True
    erp_sql_user: str = ""
    erp_sql_password: str = ""
    erp_retry_max: int = 5
    onec_sql_allowlist: str = ""
    onec_odata_entity_allowlist: str = ""


settings = OnecSettings()
logger = logging.getLogger(__name__)
_stub_counter = 0

_INCOMING_DOC_MARKERS = (
    "Document_ТД_ВходящаяКорреспонденция",
    "Document_ВходящаяКорреспонденция",
)
_TOP_RE = re.compile(r"\$top=(\d+)", re.IGNORECASE)


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


def _entity_from_request(req: ToolInvokeRequest) -> str:
    entity = str(req.payload.get("entity", "")).strip()
    if entity:
        return entity.lstrip("/")
    path = str(req.payload.get("path", "")).strip().lstrip("/")
    if not path:
        return ""
    head = path.split("?", 1)[0]
    if _is_incoming_correspondence_path(head):
        return (settings.odata_incoming_doc_entity or "Document_ТД_ВходящаяКорреспонденция").strip()
    return head


def _looks_like_odata_entity(entity: str) -> bool:
    return entity.startswith(
        ("Document_", "Catalog_", "BusinessProcess_", "InformationRegister_", "Task_")
    )


def _odata_allowlist() -> set[str]:
    return odata_entity_allowlist(settings.onec_odata_entity_allowlist)


def _sql_allowlist() -> set[str]:
    return sql_table_allowlist(settings.onec_sql_allowlist)


def _build_list_path(entity: str, top: int) -> str:
    entity = entity.strip().lstrip("/")
    return f"{entity}?$format=json&$top={top}"


def _ensure_odata_query(path: str, *, top: int | None = None) -> str:
    """1C OData requires $format=json; callers often omit it."""
    normalized = path.strip().lstrip("/")
    if "$format" not in normalized.lower():
        normalized = f"{normalized}{'&' if '?' in normalized else '?'}$format=json"
    if top is not None and "$top" not in normalized.lower():
        normalized = f"{normalized}&$top={top}"
    return normalized


def _payload_credentials(payload: dict[str, Any]) -> tuple[str, str] | None:
    username = str(
        payload.get("username") or payload.get("erp_login") or payload.get("user") or ""
    ).strip()
    password = str(
        payload.get("password") or payload.get("erp_password") or ""
    ).strip()
    if username and password:
        return username, password
    return None


def _odata_auth(req: ToolInvokeRequest | None = None) -> tuple[str, str] | None:
    """1C returns HTTP 402 for bad credentials (not «payment required»)."""
    payload = req.payload if req else {}
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
            "Укажите ERP_LOGIN/ERP_PASSWORD в infra/.env или передайте username/password в payload."
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


def _fetch_odata_list(req: ToolInvokeRequest) -> dict[str, Any]:
    """Read a list slice from real 1C OData (documents/catalogs)."""
    path = str(req.payload.get("path", "")).strip()
    entity = _entity_from_request(req)
    if not entity:
        raise ValueError("entity or path required")
    entity = validate_odata_entity(entity, allowlist=_odata_allowlist())
    top = _parse_top_limit(path, req.payload)
    cleaned_path = path.strip().lstrip("/")
    if cleaned_path and cleaned_path.split("?", 1)[0] == entity:
        odata_path = _ensure_odata_query(cleaned_path, top=top)
    else:
        odata_path = _build_list_path(entity, top)
    if not settings.odata_base_url:
        raise RuntimeError(
            "ODATA_BASE_URL не настроен. Добавьте параметры OData в infra/.env "
            "(ODATA_BASE_URL, ODATA_USERNAME, ODATA_PASSWORD)."
        )

    inner = ToolInvokeRequest(
        run_id=req.run_id,
        department=req.department,
        user_id=req.user_id,
        payload={"path": odata_path},
    )
    raw = _odata_get(inner)
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
        "value": value,
        "source": "odata",
    }


def _fetch_latest_incoming_correspondence(req: ToolInvokeRequest) -> dict[str, Any]:
    return _fetch_odata_list(req)


def _odata_get_dispatch(req: ToolInvokeRequest) -> dict[str, Any]:
    entity = _entity_from_request(req)
    path = str(req.payload.get("path", ""))
    if _is_incoming_correspondence_path(path) or _looks_like_odata_entity(entity):
        return _fetch_odata_list(req)
    return _odata_get(req)


def _stub_odata_get(req: ToolInvokeRequest) -> dict[str, Any]:
    entity = _entity_from_request(req)
    path = str(req.payload.get("path", ""))
    if _is_incoming_correspondence_path(path) or _looks_like_odata_entity(entity):
        if not entity:
            raise ValueError("entity or path required")
        entity = validate_odata_entity(entity, allowlist=_odata_allowlist())
        top = _parse_top_limit(path, req.payload)
        return stub_odata_rows(entity, top)
    path_clean = path.strip().lstrip("/")
    if path_clean:
        validate_odata_path(path_clean, allowlist=_odata_allowlist())
    return {
        "summary": "stub odata get",
        "path": path,
        "value": [{"Ref_Key": "00000000-0000-0000-0000-000000000001"}],
        "source": "stub",
    }


def _stub_odata_post(req: ToolInvokeRequest) -> dict[str, Any]:
    n = _next_stub_id()
    return {
        "summary": f"stub document {n}",
        "erp_document_number": f"ВК-STUB-{n:06d}",
        "erp_document_id": f"11111111-1111-1111-1111-{n:012d}"[:36],
    }


def _stub_odata_patch(req: ToolInvokeRequest) -> dict[str, Any]:
    return {"summary": "stub patch ok", "updated": True, "ref_key": req.payload.get("ref_key")}


def _stub_attach_file(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "stub attach",
        "ref_key": req.payload.get("document_ref_key"),
        "filename": req.payload.get("filename", "file.pdf"),
    }


def _stub_sql_query(req: ToolInvokeRequest) -> dict[str, Any]:
    sql = validate_sql_query(str(req.payload.get("sql", "")), allowlist=_sql_allowlist())
    return {
        "summary": "stub sql",
        "sql": sql,
        "rows": [{"id": 1, "name": "stub"}],
        "source": "stub",
    }


def _odata_get(req: ToolInvokeRequest) -> dict[str, Any]:
    raw_path = str(req.payload.get("path", ""))
    path = validate_odata_path(raw_path, allowlist=_odata_allowlist())
    top = _parse_top_limit(raw_path, req.payload) if raw_path else None
    path = _ensure_odata_query(path, top=top if "$top" not in path.lower() else None)
    if not settings.odata_base_url:
        raise RuntimeError("ODATA_BASE_URL not configured")
    auth = _odata_auth(req)
    if not auth:
        raise RuntimeError(
            "OData credentials not configured: set ERP_LOGIN/ERP_PASSWORD or ODATA_USERNAME/ODATA_PASSWORD"
        )
    url = f"{settings.odata_base_url.rstrip('/')}/{path}"
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.get(url, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise RuntimeError(_parse_onec_http_error(response))
        data = response.json()
    return {"summary": "odata get ok", "path": path, "data": data}


def _odata_post(req: ToolInvokeRequest) -> dict[str, Any]:
    entity = validate_odata_entity(str(req.payload.get("entity", "")), allowlist=_odata_allowlist())
    body = req.payload.get("body") or {}
    if not settings.odata_base_url:
        raise RuntimeError("ODATA_BASE_URL not configured")
    auth = _odata_auth(req)
    if not auth:
        raise RuntimeError("OData credentials not configured")
    url = f"{settings.odata_base_url.rstrip('/')}/{entity}"
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.post(url, json=body, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise RuntimeError(_parse_onec_http_error(response))
        data = response.json()
    return {
        "summary": "odata post ok",
        "erp_document_id": data.get("Ref_Key") or data.get("ref_key"),
        "data": data,
    }


def _odata_patch(req: ToolInvokeRequest) -> dict[str, Any]:
    entity = validate_odata_entity(str(req.payload.get("entity", "")), allowlist=_odata_allowlist())
    ref_key = str(req.payload.get("ref_key", "")).strip()
    body = req.payload.get("body") or {}
    if not ref_key:
        raise ValueError("ref_key required")
    url = f"{settings.odata_base_url.rstrip('/')}/{entity}(guid'{ref_key}')"
    auth = _odata_auth(req)
    if not auth:
        raise RuntimeError("OData credentials not configured")
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=auth) as client:
        response = client.patch(url, json=body, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise RuntimeError(_parse_onec_http_error(response))
    return {"summary": "odata patch ok", "updated": True, "ref_key": ref_key}


def _attach_file(req: ToolInvokeRequest) -> dict[str, Any]:
    raise ValueError(
        "NOT_IMPLEMENTED: onec.attach_file requires OData file upload — not available in this build. "
        "Use onec.odata_patch for metadata or attach files manually in 1C."
    )


def _build_connection_string() -> str:
    parts = [
        f"DRIVER={{{settings.erp_sql_driver}}}",
        f"SERVER={settings.erp_sql_server}",
        f"DATABASE={settings.erp_sql_database}",
        "Encrypt=no",
        "TrustServerCertificate=yes",
    ]
    if settings.erp_sql_trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={settings.erp_sql_user}")
        parts.append(f"PWD={settings.erp_sql_password}")
    return ";".join(parts) + ";"


def _sql_query(req: ToolInvokeRequest) -> dict[str, Any]:
    sql = validate_sql_query(str(req.payload.get("sql", "")), allowlist=_sql_allowlist())
    try:
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
    except pyodbc.Error as exc:
        if settings.use_stubs:
            return _stub_sql_query(req)
        logger.warning("SQL query failed, returning stub fallback: %s", exc)
        data = _stub_sql_query(req)
        data["warning"] = str(exc)[:500]
        data["source"] = "stub-fallback"
        return data


STUB_HANDLERS = {
    "onec.odata_get": _stub_odata_get,
    "onec.odata_post": _stub_odata_post,
    "onec.odata_patch": _stub_odata_patch,
    "onec.attach_file": _stub_attach_file,
    "onec.sql_query": _stub_sql_query,
}

REAL_HANDLERS = {
    "onec.odata_get": _odata_get_dispatch,
    "onec.odata_post": _odata_post,
    "onec.odata_patch": _odata_patch,
    "onec.attach_file": _attach_file,
    "onec.sql_query": _sql_query,
}

app = create_tool_app(settings, REAL_HANDLERS, stub_handlers=STUB_HANDLERS)


def main() -> None:
    run_app(app, settings)


if __name__ == "__main__":
    main()
