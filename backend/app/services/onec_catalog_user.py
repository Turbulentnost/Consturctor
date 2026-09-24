"""Catalog_Пользователи Ref_Key (OData GUID) for the logged-in ERP user."""

from __future__ import annotations

from typing import Any

from app.services.onec_access import sql_hex_to_odata_guid


def _is_true(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bytes):
        return any(byte != 0 for byte in value)
    if isinstance(value, (int, float)):
        return int(value) != 0
    text = str(value).strip().upper()
    return text in {"1", "01", "TRUE"}


def _looks_like_1c_hex_id(value: str) -> bool:
    text = (value or "").strip()
    if not text or "-" in text:
        return False
    return 16 <= len(text) <= 64 and all(ch in "0123456789ABCDEFabcdef" for ch in text)


def resolve_catalog_user_ref_key(*, user_id: str = "", fio: str = "") -> str:
    """Return OData GUID for _Reference366 / Catalog_Пользователи, or empty."""
    user_id = (user_id or "").strip().upper()
    fio = " ".join(str(fio or "").split())
    if not user_id and not fio:
        return ""
    try:
        from app.clients.erp_sql import ErpSqlError, _connect
    except ImportError:
        return ""
    try:
        conn = _connect()
    except ErpSqlError:
        return ""
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        row = _fetch_catalog_row(cur, user_id=user_id, fio=fio)
        if row is None:
            return ""
        hex_id = str(row.get("hex") or "").strip().upper()
        return sql_hex_to_odata_guid(hex_id) if hex_id else ""
    except Exception:  # noqa: BLE001
        return ""
    finally:
        conn.close()


def _fetch_catalog_row(cur: Any, *, user_id: str, fio: str) -> dict[str, str] | None:
    row = None
    if user_id and _looks_like_1c_hex_id(user_id):
        cur.execute(
            """
            SELECT TOP 2
                CONVERT(varchar(64), _IDRRef, 2) AS Id,
                CAST(_Description AS nvarchar(256)) AS Descr,
                _Marked AS Marked,
                _Fld10995 AS Invalid
            FROM dbo._Reference366 WITH (NOLOCK)
            WHERE CONVERT(varchar(64), _Fld11001, 2) = ?
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
    if row is None and fio:
        cur.execute(
            """
            SELECT TOP 2
                CONVERT(varchar(64), _IDRRef, 2) AS Id,
                CAST(_Description AS nvarchar(256)) AS Descr,
                _Marked AS Marked,
                _Fld10995 AS Invalid
            FROM dbo._Reference366 WITH (NOLOCK)
            WHERE LTRIM(RTRIM(_Description)) = ?
            """,
            (fio,),
        )
        rows = cur.fetchall()
        if len(rows) == 1:
            row = rows[0]
        elif len(rows) > 1:
            return None
    if row is None:
        return None
    if _is_true(getattr(row, "Marked", None)) or _is_true(getattr(row, "Invalid", None)):
        return None
    hex_id = (getattr(row, "Id", None) or "").strip().upper()
    if not hex_id:
        return None
    return {"hex": hex_id, "fio": (getattr(row, "Descr", None) or "").strip() or fio}
