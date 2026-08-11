from __future__ import annotations

import re
from typing import Any

import httpx
import pyodbc
from pydantic_settings import SettingsConfigDict

from platform_contracts.tools import ToolInvokeRequest
from platform_service_common.app_factory import ServiceSettings, create_tool_app, run_app

_SELECT_ONLY = re.compile(r"^\s*SELECT\b", re.IGNORECASE | re.DOTALL)
_FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|EXEC|MERGE)\b", re.IGNORECASE)


class OnecSettings(ServiceSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "platform-tool-onec"
    api_port: int = 7822
    odata_base_url: str = ""
    odata_username: str = ""
    odata_password: str = ""
    odata_timeout_sec: float = 60.0
    odata_incoming_doc_entity: str = "Document_ТД_ВходящаяКорреспонденция"
    erp_sql_server: str = "ii1"
    erp_sql_database: str = "erp_pm"
    erp_sql_driver: str = "ODBC Driver 18 for SQL Server"
    erp_sql_trusted_connection: bool = True
    erp_sql_user: str = ""
    erp_sql_password: str = ""
    erp_retry_max: int = 5


settings = OnecSettings()
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


def _build_list_path(entity: str, top: int) -> str:
    entity = entity.strip().lstrip("/")
    if entity.startswith("Catalog_") or entity.startswith("InformationRegister_"):
        return f"{entity}?$format=json&$top={top}"
    return f"{entity}?$format=json&$orderby=Date desc&$top={top}"


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
    top = _parse_top_limit(path, req.payload)
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
        return _fetch_odata_list(req)
    return {
        "summary": "stub odata get",
        "path": path,
        "value": [{"Ref_Key": "00000000-0000-0000-0000-000000000001"}],
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
    return {"summary": "stub sql", "rows": [{"id": 1, "name": "stub"}]}


def _odata_auth() -> tuple[str, str] | None:
    if settings.odata_username and settings.odata_password:
        return settings.odata_username, settings.odata_password
    return None


def _odata_get(req: ToolInvokeRequest) -> dict[str, Any]:
    path = str(req.payload.get("path", "")).strip().lstrip("/")
    if not path:
        raise ValueError("path required")
    if not settings.odata_base_url:
        raise RuntimeError("ODATA_BASE_URL not configured")
    url = f"{settings.odata_base_url.rstrip('/')}/{path}"
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=_odata_auth()) as client:
        response = client.get(url)
        response.raise_for_status()
        data = response.json()
    return {"summary": "odata get ok", "path": path, "data": data}


def _odata_post(req: ToolInvokeRequest) -> dict[str, Any]:
    entity = str(req.payload.get("entity", "")).strip()
    body = req.payload.get("body") or {}
    if not entity:
        raise ValueError("entity required")
    if not settings.odata_base_url:
        raise RuntimeError("ODATA_BASE_URL not configured")
    url = f"{settings.odata_base_url.rstrip('/')}/{entity}"
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=_odata_auth()) as client:
        response = client.post(url, json=body)
        response.raise_for_status()
        data = response.json()
    return {
        "summary": "odata post ok",
        "erp_document_id": data.get("Ref_Key") or data.get("ref_key"),
        "data": data,
    }


def _odata_patch(req: ToolInvokeRequest) -> dict[str, Any]:
    entity = str(req.payload.get("entity", "")).strip()
    ref_key = str(req.payload.get("ref_key", "")).strip()
    body = req.payload.get("body") or {}
    if not entity or not ref_key:
        raise ValueError("entity and ref_key required")
    url = f"{settings.odata_base_url.rstrip('/')}/{entity}(guid'{ref_key}')"
    with httpx.Client(timeout=settings.odata_timeout_sec, auth=_odata_auth()) as client:
        response = client.patch(url, json=body)
        response.raise_for_status()
    return {"summary": "odata patch ok", "updated": True, "ref_key": ref_key}


def _attach_file(req: ToolInvokeRequest) -> dict[str, Any]:
    return {
        "summary": "attach not implemented in MVP",
        "document_ref_key": req.payload.get("document_ref_key"),
        "filename": req.payload.get("filename"),
        "stub": True,
    }


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
    sql = str(req.payload.get("sql", "")).strip()
    if not sql:
        raise ValueError("sql required")
    if not _SELECT_ONLY.match(sql) or _FORBIDDEN.search(sql):
        raise ValueError("Only SELECT queries are allowed")
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
    return {"summary": f"rows={len(rows)}", "rows": rows}


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
