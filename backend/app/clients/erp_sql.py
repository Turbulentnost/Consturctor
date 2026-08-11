"""Read-only client for 1C SQL Server database erp_pm (v8users + departments)."""

from __future__ import annotations

from dataclasses import dataclass

import pyodbc

from app.config import settings

_DEPARTMENT_JOIN_SQL = """
    LEFT JOIN dbo._Reference513 d1 WITH (NOLOCK)
        ON u._Fld10996RRef = d1._IDRRef
    LEFT JOIN dbo._Reference513 d2 WITH (NOLOCK)
        ON u._Fld74621RRef = d2._IDRRef
    LEFT JOIN dbo._Reference513 d3 WITH (NOLOCK)
        ON u._Fld166077RRef = d3._IDRRef
    LEFT JOIN dbo._Reference513 d4 WITH (NOLOCK)
        ON u._Fld166081RRef = d4._IDRRef
    LEFT JOIN dbo._Reference513 d5 WITH (NOLOCK)
        ON u._Fld166082RRef = d5._IDRRef
"""

_DEPARTMENT_EXPR = """
    CAST(
        COALESCE(
            NULLIF(LTRIM(RTRIM(d1._Description)), N''),
            NULLIF(LTRIM(RTRIM(d2._Description)), N''),
            NULLIF(LTRIM(RTRIM(d3._Description)), N''),
            NULLIF(LTRIM(RTRIM(d4._Description)), N''),
            NULLIF(LTRIM(RTRIM(d5._Description)), N''),
            N''
        ) AS nvarchar(256)
    )
"""

_FIO_EXPR = "LTRIM(RTRIM(COALESCE(NULLIF(v.Descr, N''), v.Name)))"


@dataclass(frozen=True, slots=True)
class ErpUserRow:
    id: str
    name: str
    descr: str
    data: bytes | None = None
    department: str = ""

    @property
    def fio(self) -> str:
        descr = (self.descr or "").strip()
        return descr if descr else (self.name or "").strip()


@dataclass(frozen=True, slots=True)
class ErpUserProfile:
    fio: str
    department: str = ""


class ErpSqlError(Exception):
    pass


class AmbiguousUserError(ErpSqlError):
    pass


class UserNotFoundError(ErpSqlError):
    pass


def _build_connection_string() -> str:
    parts = [
        f"DRIVER={{{settings.erp_sql_driver}}}",
        f"SERVER={settings.erp_sql_server}",
        f"DATABASE={settings.erp_sql_database}",
        f"Encrypt={settings.erp_sql_encrypt}",
        "TrustServerCertificate=yes",
        "Connection Timeout=15",
    ]
    if settings.erp_sql_trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={settings.erp_sql_user}")
        parts.append(f"PWD={settings.erp_sql_password}")
    return ";".join(parts) + ";"


def _connect() -> pyodbc.Connection:
    try:
        return pyodbc.connect(_build_connection_string(), autocommit=True)
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to connect to erp_pm: {exc}") from exc


def _row_department(row) -> str:
    if row is None:
        return ""
    dept = getattr(row, "Department", None)
    if dept is None and len(row) > 1:
        dept = row[1]
    return (dept or "").strip()


def ping() -> bool:
    """Return True if ERP SQL is reachable."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        return True
    finally:
        conn.close()


def get_user_profile_by_fio(fio: str) -> ErpUserProfile:
    """FIO and department from 1C catalogs (_Reference366 + _Reference513)."""
    fio = fio.strip()
    if not fio:
        return ErpUserProfile(fio="")

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(
            f"""
            SELECT
                CAST(u._Description AS nvarchar(256)) AS Fio,
                {_DEPARTMENT_EXPR} AS Department
            FROM dbo._Reference366 u WITH (NOLOCK)
            {_DEPARTMENT_JOIN_SQL}
            WHERE LTRIM(RTRIM(u._Description)) = ?
            """,
            (fio,),
        )
        row = cur.fetchone()
        if row:
            return ErpUserProfile(fio=(row.Fio or fio).strip(), department=_row_department(row))

        cur.execute(
            f"""
            SELECT TOP 1
                CAST(p._Description AS nvarchar(256)) AS Fio,
                {_DEPARTMENT_EXPR} AS Department
            FROM dbo._Reference366 u WITH (NOLOCK)
            INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                ON u._Fld10997RRef = p._IDRRef
            {_DEPARTMENT_JOIN_SQL}
            WHERE LTRIM(RTRIM(p._Description)) = ?
            """,
            (fio,),
        )
        row = cur.fetchone()
        if row:
            return ErpUserProfile(fio=(row.Fio or fio).strip(), department=_row_department(row))

        return ErpUserProfile(fio=fio)
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to load user profile: {exc}") from exc
    finally:
        conn.close()


def find_users_by_fio(fio: str) -> list[ErpUserRow]:
    """Exact match (after trim) on Name or Descr."""
    fio = fio.strip()
    if not fio:
        return []

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(
            f"""
            SELECT
                CONVERT(varchar(64), v.ID, 2) AS UserId,
                CAST(v.Name AS nvarchar(128)) AS Name,
                CAST(v.Descr AS nvarchar(256)) AS Descr,
                v.Data,
                {_DEPARTMENT_EXPR} AS Department
            FROM dbo.v8users v WITH (NOLOCK)
            LEFT JOIN dbo._Reference366 u WITH (NOLOCK)
                ON LTRIM(RTRIM(u._Description)) = LTRIM(RTRIM(COALESCE(NULLIF(v.Descr, N''), v.Name)))
            {_DEPARTMENT_JOIN_SQL}
            WHERE LTRIM(RTRIM(v.Name)) = ? OR LTRIM(RTRIM(v.Descr)) = ?
            """,
            (fio, fio),
        )
        rows: list[ErpUserRow] = []
        for row in cur.fetchall():
            rows.append(
                ErpUserRow(
                    id=(row.UserId or "").strip().upper(),
                    name=(row.Name or "").strip(),
                    descr=(row.Descr or "").strip(),
                    data=bytes(row.Data) if row.Data is not None else b"",
                    department=_row_department(row),
                )
            )
        return rows
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to query v8users: {exc}") from exc
    finally:
        conn.close()


def find_user_by_fio(fio: str) -> ErpUserRow:
    rows = find_users_by_fio(fio)
    if not rows:
        raise UserNotFoundError("User not found")
    unique: dict[str, ErpUserRow] = {r.id: r for r in rows}
    if len(unique) > 1:
        raise AmbiguousUserError("Multiple users match this FIO")
    user = next(iter(unique.values()))
    if not user.department:
        profile = get_user_profile_by_fio(user.fio)
        if profile.department:
            return ErpUserRow(
                id=user.id,
                name=user.name,
                descr=user.descr,
                data=user.data,
                department=profile.department,
            )
    return user


def find_user_by_id(user_id: str) -> ErpUserRow | None:
    user_id = (user_id or "").strip().upper()
    if not user_id:
        return None

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(
            f"""
            SELECT
                CONVERT(varchar(64), v.ID, 2) AS UserId,
                CAST(v.Name AS nvarchar(128)) AS Name,
                CAST(v.Descr AS nvarchar(256)) AS Descr,
                {_DEPARTMENT_EXPR} AS Department
            FROM dbo.v8users v WITH (NOLOCK)
            LEFT JOIN dbo._Reference366 u WITH (NOLOCK)
                ON LTRIM(RTRIM(u._Description)) = LTRIM(RTRIM(COALESCE(NULLIF(v.Descr, N''), v.Name)))
            {_DEPARTMENT_JOIN_SQL}
            WHERE CONVERT(varchar(64), v.ID, 2) = ?
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        user = ErpUserRow(
            id=(row.UserId or "").strip().upper(),
            name=(row.Name or "").strip(),
            descr=(row.Descr or "").strip(),
            data=None,
            department=_row_department(row),
        )
        if not user.department:
            profile = get_user_profile_by_fio(user.fio)
            if profile.department:
                return ErpUserRow(
                    id=user.id,
                    name=user.name,
                    descr=user.descr,
                    data=None,
                    department=profile.department,
                )
        return user
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to query v8users by id: {exc}") from exc
    finally:
        conn.close()


def search_user_fios(search: str | None = None, limit: int = 200) -> list[str]:
    """Search FIO catalog in erp_pm (read-only). Empty search returns first N names."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        term = (search or "").strip()

        if term:
            # Prefix on whole FIO or any word — avoids "Ман" matching inside "Романовна".
            starts = f"{term}%"
            word_starts = f"% {term}%"
            cur.execute(
                f"""
                SELECT DISTINCT TOP (?) {_FIO_EXPR} AS Fio
                FROM dbo.v8users v WITH (NOLOCK)
                WHERE {_FIO_EXPR} LIKE ?
                   OR {_FIO_EXPR} LIKE ?
                   OR LTRIM(RTRIM(v.Name)) LIKE ?
                   OR LTRIM(RTRIM(v.Name)) LIKE ?
                   OR LTRIM(RTRIM(v.Descr)) LIKE ?
                   OR LTRIM(RTRIM(v.Descr)) LIKE ?
                ORDER BY Fio
                """,
                (limit, starts, word_starts, starts, word_starts, starts, word_starts),
            )
        else:
            cur.execute(
                f"""
                SELECT DISTINCT TOP (?) {_FIO_EXPR} AS Fio
                FROM dbo.v8users v WITH (NOLOCK)
                WHERE {_FIO_EXPR} <> N''
                ORDER BY Fio
                """,
                (limit,),
            )

        return [(row.Fio or "").strip() for row in cur.fetchall() if (row.Fio or "").strip()]
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to search v8users: {exc}") from exc
    finally:
        conn.close()


def list_departments(limit: int = 500) -> list[str]:
    """Distinct department names from 1C catalog _Reference513."""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(
            """
            SELECT DISTINCT TOP (?)
                LTRIM(RTRIM(d._Description)) AS Dept
            FROM dbo._Reference513 d WITH (NOLOCK)
            WHERE LTRIM(RTRIM(d._Description)) <> N''
            ORDER BY Dept
            """,
            (limit,),
        )
        return [(row.Dept or "").strip() for row in cur.fetchall() if (row.Dept or "").strip()]
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to list departments: {exc}") from exc
    finally:
        conn.close()
