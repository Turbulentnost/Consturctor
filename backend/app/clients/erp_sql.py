"""Read-only client for 1C SQL Server database erp_pm (v8users + departments + positions)."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
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

# Current staff assignment: person (_Reference596) -> InfoRg43757 -> position (_Reference164).
# Open-ended assignments use DateTo near year 5999 (1C empty/infinite date).
_POSITION_BY_FIO_SQL = """
    SELECT TOP 1
        CAST(pos._Description AS nvarchar(256)) AS Position
    FROM dbo._Reference596 person WITH (NOLOCK)
    INNER JOIN dbo._InfoRg43757 t WITH (NOLOCK)
        ON t._Fld43761RRef = person._IDRRef
    INNER JOIN dbo._Reference164 pos WITH (NOLOCK)
        ON t._Fld43766RRef = pos._IDRRef
    WHERE LTRIM(RTRIM(person._Description)) = ?
      AND LTRIM(RTRIM(pos._Description)) <> N''
      AND t._Fld43775 >= '5999-01-01'
    ORDER BY t._Fld43774 DESC
"""

_POSITION_BY_FIO_FALLBACK_SQL = """
    SELECT TOP 1
        CAST(pos._Description AS nvarchar(256)) AS Position
    FROM dbo._Reference596 person WITH (NOLOCK)
    INNER JOIN dbo._InfoRg43757 t WITH (NOLOCK)
        ON t._Fld43761RRef = person._IDRRef
    INNER JOIN dbo._Reference164 pos WITH (NOLOCK)
        ON t._Fld43766RRef = pos._IDRRef
    WHERE LTRIM(RTRIM(person._Description)) = ?
      AND LTRIM(RTRIM(pos._Description)) <> N''
    ORDER BY t._Fld43774 DESC
"""

_FIO_EXPR = "LTRIM(RTRIM(COALESCE(NULLIF(v.Descr, N''), v.Name)))"


@dataclass(frozen=True, slots=True)
class ErpUserRow:
    id: str
    name: str
    descr: str
    data: bytes | None = None
    department: str = ""
    position: str = ""

    @property
    def fio(self) -> str:
        descr = (self.descr or "").strip()
        return descr if descr else (self.name or "").strip()


@dataclass(frozen=True, slots=True)
class ErpUserProfile:
    fio: str
    department: str = ""
    position: str = ""


@dataclass(frozen=True, slots=True)
class ErpOrgDept:
    id: str
    name: str
    parent_id: str
    is_root: bool = False
    head_fio: str = ""


@dataclass(frozen=True, slots=True)
class ErpSubordinate:
    fio: str
    position: str
    department: str


class ErpSqlError(Exception):
    pass


class AmbiguousUserError(ErpSqlError):
    pass


class UserNotFoundError(ErpSqlError):
    pass


_PREFERRED_ODBC_DRIVERS = (
    "ODBC Driver 18 for SQL Server",
    "ODBC Driver 17 for SQL Server",
    "SQL Server",
)


def resolve_odbc_driver(configured: str) -> str:
    """Pick an installed ODBC driver; configured name wins if present."""
    installed = pyodbc.drivers()
    configured = (configured or "").strip()
    if configured and configured in installed:
        return configured
    for name in _PREFERRED_ODBC_DRIVERS:
        if name in installed:
            return name
    if configured:
        return configured
    available = ", ".join(installed) if installed else "нет установленных драйверов"
    raise ErpSqlError(
        f"ODBC driver not found ({configured or 'auto'}). Installed: {available}"
    )


def _parse_domain_user(user: str) -> tuple[str, str]:
    if "\\" in user:
        domain, username = user.split("\\", 1)
        return domain, username
    if "@" in user:
        username, domain = user.split("@", 1)
        return domain, username
    return "", user


@contextmanager
def _windows_impersonation(user: str, password: str) -> Generator[None, None, None]:
    """Impersonate a Windows account for Trusted_Connection (как в Constructor)."""
    import win32con
    import win32security

    domain, username = _parse_domain_user(user)
    logon_types = (
        win32con.LOGON32_LOGON_NEW_CREDENTIALS,
        win32con.LOGON32_LOGON_NETWORK,
        win32con.LOGON32_LOGON_INTERACTIVE,
    )

    last_error: Exception | None = None
    token = None
    for logon_type in logon_types:
        try:
            token = win32security.LogonUser(
                username,
                domain or None,
                password,
                logon_type,
                win32con.LOGON32_PROVIDER_DEFAULT,
            )
            break
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            token = None

    if token is None:
        raise ErpSqlError(f"Windows LogonUser failed for {user!r}: {last_error}")

    win32security.ImpersonateLoggedOnUser(token)
    try:
        yield
    finally:
        win32security.RevertToSelf()
        token.Close()


def _use_windows_impersonation() -> bool:
    """Domain user + password → Trusted_Connection under impersonation."""
    return bool(settings.erp_sql_user.strip() and settings.erp_sql_password)


def _build_connection_string() -> str:
    driver = resolve_odbc_driver(settings.erp_sql_driver)
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={settings.erp_sql_server}",
        f"DATABASE={settings.erp_sql_database}",
        f"Encrypt={settings.erp_sql_encrypt}",
        "TrustServerCertificate=yes",
        "Connection Timeout=15",
    ]
    if _use_windows_impersonation() or settings.erp_sql_trusted_connection:
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={settings.erp_sql_user}")
        parts.append(f"PWD={settings.erp_sql_password}")
    return ";".join(parts) + ";"


def _connect() -> pyodbc.Connection:
    try:
        if _use_windows_impersonation():
            with _windows_impersonation(settings.erp_sql_user, settings.erp_sql_password):
                return pyodbc.connect(_build_connection_string(), autocommit=True)
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


def _row_position(row) -> str:
    if row is None:
        return ""
    position = getattr(row, "Position", None)
    return (position or "").strip()


def get_position_by_fio(fio: str) -> str:
    """Current job title from HR register (_InfoRg43757 + _Reference164)."""
    fio = fio.strip()
    if not fio:
        return ""
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(_POSITION_BY_FIO_SQL, (fio,))
        row = cur.fetchone()
        if row and _row_position(row):
            return _row_position(row)
        cur.execute(_POSITION_BY_FIO_FALLBACK_SQL, (fio,))
        row = cur.fetchone()
        return _row_position(row)
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to load position: {exc}") from exc
    finally:
        conn.close()


def ping() -> bool:
    """Return True if ERP SQL is reachable."""
    try:
        resolve_odbc_driver(settings.erp_sql_driver)
    except ErpSqlError as exc:
        raise ErpSqlError(str(exc)) from exc
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        return True
    finally:
        conn.close()


def get_user_profile_by_fio(fio: str) -> ErpUserProfile:
    """FIO, department and position from 1C catalogs / HR registers."""
    fio = fio.strip()
    if not fio:
        return ErpUserProfile(fio="")

    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        department = ""
        resolved_fio = fio
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
            resolved_fio = (row.Fio or fio).strip()
            department = _row_department(row)
        else:
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
                resolved_fio = (row.Fio or fio).strip()
                department = _row_department(row)

        position = ""
        cur.execute(_POSITION_BY_FIO_SQL, (resolved_fio,))
        pos_row = cur.fetchone()
        if pos_row and _row_position(pos_row):
            position = _row_position(pos_row)
        else:
            cur.execute(_POSITION_BY_FIO_FALLBACK_SQL, (resolved_fio,))
            pos_row = cur.fetchone()
            position = _row_position(pos_row)
        return ErpUserProfile(fio=resolved_fio, department=department, position=position)
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
    if not user.department or not user.position:
        profile = get_user_profile_by_fio(user.fio)
        return ErpUserRow(
            id=user.id,
            name=user.name,
            descr=user.descr,
            data=user.data,
            department=user.department or profile.department,
            position=user.position or profile.position,
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
        if not user.department or not user.position:
            profile = get_user_profile_by_fio(user.fio)
            return ErpUserRow(
                id=user.id,
                name=user.name,
                descr=user.descr,
                data=None,
                department=user.department or profile.department,
                position=user.position or profile.position,
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


def _append_missing_heads(
    cur,
    manager_fio: str,
    departments: list[ErpOrgDept],
    people: list[ErpSubordinate],
    seen_people: set[str],
) -> list[ErpSubordinate]:
    missing = []
    for dept in departments:
        head = dept.head_fio
        if not head or head == manager_fio or head in seen_people:
            continue
        if head not in missing:
            missing.append(head)
    if not missing:
        return people
    placeholders = ",".join("?" * len(missing))
    cur.execute(
        f"""
        ;WITH latest AS (
            SELECT
                CAST(p._Description AS nvarchar(256)) AS Person,
                CAST(pos._Description AS nvarchar(256)) AS Position,
                CAST(hr._Description AS nvarchar(256)) AS HrDept,
                ROW_NUMBER() OVER (
                    PARTITION BY p._IDRRef
                    ORDER BY t._Fld43774 DESC
                ) AS rn
            FROM dbo._InfoRg43757 t WITH (NOLOCK)
            INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                ON t._Fld43761RRef = p._IDRRef
            LEFT JOIN dbo._Reference164 pos WITH (NOLOCK)
                ON t._Fld43766RRef = pos._IDRRef
            LEFT JOIN dbo._Reference358 hr WITH (NOLOCK)
                ON t._Fld43765RRef = hr._IDRRef
            WHERE t._Fld43775 >= '5999-01-01'
              AND t._Fld43774 > '2002-01-01'
              AND LTRIM(RTRIM(p._Description)) IN ({placeholders})
        )
        SELECT Person, Position, HrDept
        FROM latest
        WHERE rn = 1
        """,
        missing,
    )
    found: dict[str, tuple[str, str]] = {}
    for row in cur.fetchall():
        found[(row.Person or "").strip()] = (
            (row.Position or "").strip(),
            (row.HrDept or "").strip(),
        )
    extra: list[ErpSubordinate] = []
    for head in missing:
        position, department = found.get(head, ("", ""))
        if not department:
            department = next((d.name for d in departments if d.head_fio == head), "")
        extra.append(ErpSubordinate(fio=head, position=position, department=department))
        seen_people.add(head)
    return people + extra


def load_subordinate_org(fio: str) -> tuple[ErpUserProfile, list[ErpOrgDept], list[ErpSubordinate]]:
    """Active people under departments headed by FIO (erp_pm org + staffing).

    Skips dismissed/transferred: only the latest open staffing assignment
    (DateTo >= 5999, DateFrom after 2002) still inside the headed subtree.
    Co-holders of the manager's own staff unit are excluded.
    """
    fio = fio.strip()
    if not fio:
        return ErpUserProfile(fio=""), [], []

    profile = get_user_profile_by_fio(fio)
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(
            """
            ;WITH headed AS (
                SELECT d._IDRRef, d._Description, d._ParentIDRRef, d._Fld14523RRef
                FROM dbo._Reference513 d WITH (NOLOCK)
                INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                    ON d._Fld14523RRef = p._IDRRef
                WHERE LTRIM(RTRIM(p._Description)) = ?
                  AND d._Marked = 0x00
                  AND LTRIM(RTRIM(d._Description)) <> N''
            ),
            tree AS (
                SELECT _IDRRef, _Description, _ParentIDRRef, _Fld14523RRef, CAST(1 AS int) AS IsRoot
                FROM headed
                UNION ALL
                SELECT c._IDRRef, c._Description, c._ParentIDRRef, c._Fld14523RRef, 0
                FROM dbo._Reference513 c WITH (NOLOCK)
                INNER JOIN tree t ON c._ParentIDRRef = t._IDRRef
                WHERE c._Marked = 0x00
                  AND LTRIM(RTRIM(c._Description)) <> N''
            )
            SELECT
                CONVERT(varchar(64), t._IDRRef, 2) AS DeptId,
                CAST(t._Description AS nvarchar(256)) AS Dept,
                CONVERT(varchar(64), t._ParentIDRRef, 2) AS ParentId,
                t.IsRoot,
                CAST(hp._Description AS nvarchar(256)) AS HeadFio
            FROM tree t
            LEFT JOIN dbo._Reference596 hp WITH (NOLOCK)
                ON t._Fld14523RRef = hp._IDRRef
            OPTION (MAXRECURSION 32)
            """,
            (fio,),
        )
        departments: list[ErpOrgDept] = []
        dept_names: list[str] = []
        seen_depts: set[str] = set()
        for row in cur.fetchall():
            name = (row.Dept or "").strip()
            dept_id = (row.DeptId or "").strip().upper()
            if not name or dept_id in seen_depts:
                continue
            seen_depts.add(dept_id)
            departments.append(
                ErpOrgDept(
                    id=dept_id,
                    name=name,
                    parent_id=(row.ParentId or "").strip().upper(),
                    is_root=int(row.IsRoot or 0) == 1,
                    head_fio=(row.HeadFio or "").strip(),
                )
            )
            if name not in dept_names:
                dept_names.append(name)

        if not dept_names:
            return profile, [], []

        cur.execute(
            """
            SELECT TOP 1 CONVERT(varchar(64), t._Fld43767RRef, 2) AS StaffId
            FROM dbo._Reference596 p WITH (NOLOCK)
            INNER JOIN dbo._InfoRg43757 t WITH (NOLOCK)
                ON t._Fld43761RRef = p._IDRRef
            INNER JOIN dbo._Reference613X1 s WITH (NOLOCK)
                ON t._Fld43767RRef = s._IDRRef
            WHERE LTRIM(RTRIM(p._Description)) = ?
              AND t._Fld43775 >= '5999-01-01'
              AND t._Fld43774 > '2002-01-01'
              AND LTRIM(RTRIM(s._Description)) <> N''
            ORDER BY t._Fld43774 DESC
            """,
            (fio,),
        )
        staff_row = cur.fetchone()
        manager_staff_id = ((staff_row.StaffId or "").strip().upper() if staff_row else "")

        placeholders = ",".join("?" * len(dept_names))
        cur.execute(
            f"""
            ;WITH latest AS (
                SELECT
                    CAST(p._Description AS nvarchar(256)) AS Person,
                    CAST(pos._Description AS nvarchar(256)) AS Position,
                    CAST(hr._Description AS nvarchar(256)) AS HrDept,
                    CAST(folder._Description AS nvarchar(256)) AS StaffFolder,
                    CONVERT(varchar(64), t._Fld43767RRef, 2) AS StaffId,
                    ROW_NUMBER() OVER (
                        PARTITION BY p._IDRRef
                        ORDER BY t._Fld43774 DESC
                    ) AS rn
                FROM dbo._InfoRg43757 t WITH (NOLOCK)
                INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                    ON t._Fld43761RRef = p._IDRRef
                INNER JOIN dbo._Reference613X1 s WITH (NOLOCK)
                    ON t._Fld43767RRef = s._IDRRef
                LEFT JOIN dbo._Reference613X1 folder WITH (NOLOCK)
                    ON s._ParentIDRRef = folder._IDRRef
                LEFT JOIN dbo._Reference164 pos WITH (NOLOCK)
                    ON t._Fld43766RRef = pos._IDRRef
                LEFT JOIN dbo._Reference358 hr WITH (NOLOCK)
                    ON t._Fld43765RRef = hr._IDRRef
                WHERE t._Fld43775 >= '5999-01-01'
                  AND t._Fld43774 > '2002-01-01'
                  AND LTRIM(RTRIM(ISNULL(s._Description, N''))) <> N''
            )
            SELECT Person, Position, HrDept, StaffFolder, StaffId
            FROM latest
            WHERE rn = 1
              AND LTRIM(RTRIM(Person)) <> ?
              AND (
                    LTRIM(RTRIM(ISNULL(HrDept, N''))) IN ({placeholders})
                 OR LTRIM(RTRIM(ISNULL(StaffFolder, N''))) IN ({placeholders})
              )
            ORDER BY Person
            """,
            [fio, *dept_names, *dept_names],
        )
        name_set = set(dept_names)
        people: list[ErpSubordinate] = []
        seen_people: set[str] = set()
        for row in cur.fetchall():
            person = (row.Person or "").strip()
            staff_id = (row.StaffId or "").strip().upper()
            if not person or person in seen_people:
                continue
            if manager_staff_id and staff_id == manager_staff_id:
                continue
            hr_dept = (row.HrDept or "").strip()
            folder = (row.StaffFolder or "").strip()
            department = hr_dept if hr_dept in name_set else (folder if folder in name_set else hr_dept or folder)
            seen_people.add(person)
            people.append(
                ErpSubordinate(
                    fio=person,
                    position=(row.Position or "").strip(),
                    department=department,
                )
            )
        people = _append_missing_heads(cur, fio, departments, people, seen_people)
        return profile, departments, people
    except pyodbc.Error as exc:
        raise ErpSqlError(f"Failed to load subordinates: {exc}") from exc
    finally:
        conn.close()
