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
