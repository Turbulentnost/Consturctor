"""
Read-only export of 1C platform users from SQL Server database erp_pm.

Writes Login, DisplayName, Email (if discovered), OSName, PasswordDataHex to a TSV file.
Never executes INSERT/UPDATE/DELETE/DDL.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import pyodbc
except ImportError:
    print("Install dependency: python -m pip install pyodbc", file=sys.stderr)
    raise

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):  # type: ignore[misc]
        return False


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|MERGE|EXEC|EXECUTE|GRANT|REVOKE|BACKUP|RESTORE)\b",
    re.IGNORECASE,
)


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


@dataclass
class UserRow:
    user_id: str
    login: str
    display_name: str
    os_name: str
    password_data_hex: str
    email: str = ""
    department: str = ""


@dataclass
class EmailCandidate:
    table_name: str
    email_column: str
    key_column: str
    key_kind: str  # name | binary_id
    sample_hits: int = 0


@dataclass
class ExportResult:
    users: list[UserRow] = field(default_factory=list)
    email_source: str = ""
    notes: list[str] = field(default_factory=list)


def assert_select_only(sql: str) -> str:
    stripped = sql.strip().lstrip("(")
    upper = stripped.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH") or upper.startswith("SET ")):
        raise ValueError(f"Only SELECT/WITH/SET allowed, got: {sql[:80]!r}")
    # Allow SET TRANSACTION / SET NOCOUNT; still forbid DML keywords elsewhere
    if upper.startswith("SET "):
        return sql
    if FORBIDDEN_SQL.search(sql):
        raise ValueError(f"Forbidden SQL keyword detected: {sql[:120]!r}")
    return sql


def load_config(env_path: Path | None = None) -> dict[str, str]:
    env_file = env_path or (SCRIPT_DIR / ".env")
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv(SCRIPT_DIR / ".env.example")

    return {
        "server": os.getenv("DB_SERVER", "ii1"),
        "database": os.getenv("DB_NAME", "erp_pm"),
        "trusted": os.getenv("TrustedConnection", "yes").lower() in {"1", "true", "yes", "y"},
        "user": os.getenv("DB_USER", ""),
        "password": os.getenv("DB_PASSWORD", ""),
        "driver": os.getenv("ODBC_DRIVER", "ODBC Driver 18 for SQL Server"),
        "output": os.getenv(
            "OUTPUT_PATH", "backend/scripts/exports/erp_pm_users_export.txt"
        ),
    }


def build_connection_string(cfg: dict[str, str]) -> str:
    parts = [
        f"DRIVER={{{cfg['driver']}}}",
        f"SERVER={cfg['server']}",
        f"DATABASE={cfg['database']}",
        "Encrypt=no",
        "TrustServerCertificate=yes",
        "Connection Timeout=15",
        "ApplicationIntent=ReadOnly",
    ]
    if cfg["trusted"]:
        parts.append("Trusted_Connection=yes")
    else:
        if not cfg["user"]:
            raise SystemExit("DB_USER is required when TrustedConnection=no")
        parts.append(f"UID={cfg['user']}")
        parts.append(f"PWD={cfg['password']}")
    return ";".join(parts)


def connect(cfg: dict[str, str]) -> pyodbc.Connection:
    conn_str = build_connection_string(cfg)
    conn = pyodbc.connect(conn_str, autocommit=True)
    # Read-only session hints (no writes)
    cursor = conn.cursor()
    cursor.execute(assert_select_only("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"))
    cursor.execute(assert_select_only("SET NOCOUNT ON"))
    cursor.close()
    return conn


def fetchall(conn: pyodbc.Connection, sql: str, params: tuple | list = ()) -> list[pyodbc.Row]:
    sql = assert_select_only(sql)
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        if cursor.description is None:
            return []
        return cursor.fetchall()
    finally:
        cursor.close()


def fetchone(conn: pyodbc.Connection, sql: str, params: tuple | list = ()):
    rows = fetchall(conn, sql, params)
    return rows[0] if rows else None


def ensure_v8users(conn: pyodbc.Connection) -> str:
    row = fetchone(
        conn,
        """
        SELECT TABLE_SCHEMA, TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND LOWER(TABLE_NAME) = 'v8users'
        """,
    )
    if not row:
        raise SystemExit("Table v8users not found in database — is this a 1C SQL Server IB?")
    return f"[{row.TABLE_SCHEMA}].[{row.TABLE_NAME}]"


def load_users(conn: pyodbc.Connection, table: str) -> list[UserRow]:
    # CONVERT style 2 = hex without 0x; department via employee catalog join
    sql = f"""
        SELECT
            CONVERT(varchar(64), v.ID, 2) AS UserId,
            CAST(v.Name AS nvarchar(128)) AS Login,
            CAST(v.Descr AS nvarchar(256)) AS DisplayName,
            CAST(ISNULL(v.OSName, N'') AS nvarchar(256)) AS OSName,
            CONVERT(varchar(max), v.Data, 2) AS PasswordDataHex,
            {_DEPARTMENT_EXPR} AS Department
        FROM {table} v WITH (NOLOCK)
        LEFT JOIN dbo._Reference366 u WITH (NOLOCK)
            ON LTRIM(RTRIM(u._Description)) =
               LTRIM(RTRIM(COALESCE(NULLIF(v.Descr, N''), v.Name)))
        {_DEPARTMENT_JOIN_SQL}
        ORDER BY v.Name
    """
    rows = fetchall(conn, sql)
    users: list[UserRow] = []
    for r in rows:
        users.append(
            UserRow(
                user_id=(r.UserId or "").strip(),
                login=(r.Login or "").strip(),
                display_name=(r.DisplayName or "").strip(),
                os_name=(r.OSName or "").strip(),
                password_data_hex=(r.PasswordDataHex or "").strip(),
                department=(getattr(r, "Department", None) or "").strip(),
            )
        )
    return users


def discover_email_columns(conn: pyodbc.Connection) -> list[tuple[str, str, str]]:
    """Return list of (schema, table, column) with mail-like names."""
    rows = fetchall(
        conn,
        """
        SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE (
                LOWER(COLUMN_NAME) LIKE '%mail%'
             OR LOWER(COLUMN_NAME) LIKE '%email%'
             OR LOWER(COLUMN_NAME) LIKE '%e_mail%'
             OR COLUMN_NAME LIKE N'%адрес%почт%'
             OR COLUMN_NAME LIKE N'%Почт%'
        )
          AND DATA_TYPE IN ('nvarchar', 'varchar', 'nchar', 'char', 'ntext', 'text')
          AND TABLE_NAME NOT LIKE 'sys%'
        ORDER BY TABLE_NAME, COLUMN_NAME
        """,
    )
    return [(r.TABLE_SCHEMA, r.TABLE_NAME, r.COLUMN_NAME) for r in rows]


def table_columns(conn: pyodbc.Connection, schema: str, table: str) -> list[str]:
    rows = fetchall(
        conn,
        """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        """,
        (schema, table),
    )
    return [r.COLUMN_NAME for r in rows]


def pick_key_column(columns: list[str]) -> tuple[str, str] | None:
    lower_map = {c.lower(): c for c in columns}
    for candidate in ("_description", "description", "name", "_code", "code"):
        if candidate in lower_map:
            return lower_map[candidate], "name"
    # 1C reference tables usually have _IDRRef as PK
    for candidate in ("_idrref", "idrref"):
        if candidate in lower_map:
            return lower_map[candidate], "binary_id"
    return None


def score_email_column(
    conn: pyodbc.Connection, schema: str, table: str, email_col: str, key_col: str
) -> int:
    # Count rows that look like emails (contain @)
    sql = f"""
        SELECT COUNT(*) AS Cnt
        FROM [{schema}].[{table}]
        WHERE [{email_col}] LIKE N'%@%.%'
          AND LEN(CAST([{email_col}] AS nvarchar(400))) BETWEEN 5 AND 320
    """
    try:
        row = fetchone(conn, sql)
        return int(row.Cnt) if row else 0
    except pyodbc.Error:
        return 0


def find_best_email_source(conn: pyodbc.Connection) -> EmailCandidate | None:
    candidates: list[EmailCandidate] = []
    for schema, table, email_col in discover_email_columns(conn):
        cols = table_columns(conn, schema, table)
        key = pick_key_column(cols)
        if not key:
            continue
        key_col, key_kind = key
        hits = score_email_column(conn, schema, table, email_col, key_col)
        if hits <= 0:
            continue
        candidates.append(
            EmailCandidate(
                table_name=f"[{schema}].[{table}]",
                email_column=email_col,
                key_column=key_col,
                key_kind=key_kind,
                sample_hits=hits,
            )
        )

    if not candidates:
        # Heuristic: scan a few _Reference* tables for @ in nvarchar fields
        ref_tables = fetchall(
            conn,
            """
            SELECT TOP 80 TABLE_SCHEMA, TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
              AND (
                    TABLE_NAME LIKE '\\_Reference%' ESCAPE '\\'
                 OR TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
              )
            ORDER BY TABLE_NAME
            """,
        )
        for r in ref_tables:
            cols = table_columns(conn, r.TABLE_SCHEMA, r.TABLE_NAME)
            text_cols = [
                c
                for c in cols
                if c.lower().startswith("_fld") or "mail" in c.lower() or "descr" in c.lower()
            ]
            key = pick_key_column(cols)
            if not key:
                continue
            key_col, key_kind = key
            for email_col in text_cols[:12]:
                hits = score_email_column(conn, r.TABLE_SCHEMA, r.TABLE_NAME, email_col, key_col)
                if hits >= 3:
                    candidates.append(
                        EmailCandidate(
                            table_name=f"[{r.TABLE_SCHEMA}].[{r.TABLE_NAME}]",
                            email_column=email_col,
                            key_column=key_col,
                            key_kind=key_kind,
                            sample_hits=hits,
                        )
                    )

    if not candidates:
        return None
    candidates.sort(key=lambda c: c.sample_hits, reverse=True)
    return candidates[0]


def load_email_map(conn: pyodbc.Connection, source: EmailCandidate) -> dict[str, str]:
    """Map login/name (lower) or hex id -> email."""
    sql = f"""
        SELECT
            CAST([{source.key_column}] AS nvarchar(400)) AS MapKey,
            CONVERT(varchar(64), [{source.key_column}], 2) AS MapKeyHex,
            CAST([{source.email_column}] AS nvarchar(400)) AS Email
        FROM {source.table_name}
        WHERE [{source.email_column}] LIKE N'%@%.%'
    """
    mapping: dict[str, str] = {}
    try:
        rows = fetchall(conn, sql)
    except pyodbc.Error:
        # binary key may not cast to nvarchar — try hex-only
        sql = f"""
            SELECT
                CONVERT(varchar(64), [{source.key_column}], 2) AS MapKeyHex,
                CAST([{source.email_column}] AS nvarchar(400)) AS Email
            FROM {source.table_name}
            WHERE [{source.email_column}] LIKE N'%@%.%'
        """
        rows = fetchall(conn, sql)
        for r in rows:
            email = (r.Email or "").strip()
            hex_key = (r.MapKeyHex or "").strip().lower()
            if email and hex_key:
                mapping[hex_key] = email
        return mapping

    for r in rows:
        email = (getattr(r, "Email", None) or "").strip()
        if not email or "@" not in email:
            continue
        text_key = (getattr(r, "MapKey", None) or "").strip().lower()
        hex_key = (getattr(r, "MapKeyHex", None) or "").strip().lower()
        if text_key and not text_key.startswith("0x"):
            mapping[text_key] = email
        if hex_key:
            mapping[hex_key] = email
    return mapping


def attach_emails(users: list[UserRow], email_map: dict[str, str]) -> int:
    matched = 0
    for u in users:
        email = (
            email_map.get(u.login.lower())
            or email_map.get(u.display_name.lower())
            or email_map.get(u.user_id.lower())
        )
        if email:
            u.email = email
            matched += 1
    return matched


def write_tsv(path: Path, users: list[UserRow], email_source: str, notes: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 BOM for Excel
    with path.open("w", encoding="utf-8-sig", newline="\n") as f:
        f.write("# Read-only export from 1C SQL Server table v8users\n")
        f.write("# PasswordDataHex = CONVERT(Data, style 2); plaintext passwords are not stored\n")
        if email_source:
            f.write(f"# Email source: {email_source}\n")
        for note in notes:
            f.write(f"# {note}\n")
        f.write("Login\tDisplayName\tEmail\tDepartment\tOSName\tUserIdHex\tPasswordDataHex\n")
        for u in users:
            def esc(value: str) -> str:
                return (value or "").replace("\t", " ").replace("\r", " ").replace("\n", " ")

            f.write(
                "\t".join(
                    [
                        esc(u.login),
                        esc(u.display_name),
                        esc(u.email),
                        esc(u.department),
                        esc(u.os_name),
                        esc(u.user_id),
                        esc(u.password_data_hex),
                    ]
                )
                + "\n"
            )


def run_export(cfg: dict[str, str], skip_email: bool = False) -> ExportResult:
    result = ExportResult()
    print(f"Connecting to {cfg['server']} / {cfg['database']} (read-only)...")
    conn = connect(cfg)
    try:
        table = ensure_v8users(conn)
        count_row = fetchone(conn, f"SELECT COUNT(*) AS Cnt FROM {table}")
        count = int(count_row.Cnt) if count_row else 0
        print(f"Found {table}, users count = {count}")

        users = load_users(conn, table)
        result.users = users
        print(f"Loaded {len(users)} users from v8users")

        if not skip_email:
            print("Discovering email columns...")
            source = find_best_email_source(conn)
            if source:
                result.email_source = (
                    f"{source.table_name}.{source.email_column} "
                    f"(key={source.key_column}, hits≈{source.sample_hits})"
                )
                print(f"Using email source: {result.email_source}")
                email_map = load_email_map(conn, source)
                matched = attach_emails(users, email_map)
                result.notes.append(f"Email matched for {matched}/{len(users)} users")
                print(f"Email matched: {matched}/{len(users)}")
            else:
                result.notes.append("Email columns with data not found; Email column left empty")
                print("Email: not found (column left empty)")
        else:
            result.notes.append("Email discovery skipped by flag")

        return result
    finally:
        conn.close()
        print("Connection closed (no writes performed)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only export of 1C users from erp_pm")
    parser.add_argument("--env", type=Path, default=None, help="Path to .env file")
    parser.add_argument("--output", type=Path, default=None, help="Output TSV path")
    parser.add_argument("--skip-email", action="store_true", help="Skip email discovery")
    parser.add_argument("--server", default=None, help="Override DB_SERVER")
    args = parser.parse_args(argv)

    cfg = load_config(args.env)
    if args.server:
        cfg["server"] = args.server

    out = Path(args.output) if args.output else (REPO_ROOT / cfg["output"])
    if not out.is_absolute():
        out = REPO_ROOT / out

    result = run_export(cfg, skip_email=args.skip_email)
    write_tsv(out, result.users, result.email_source, result.notes)

    print(f"Wrote {len(result.users)} users -> {out}")
    print(f"{len(result.users)} users exported, read-only, 0 writes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
