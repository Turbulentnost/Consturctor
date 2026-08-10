"""
Проверка пароля 1С по полю v8users.Data.

CLI-обёртка над tools.onec.password.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from tools.onec.password import verify_password_details  # noqa: E402


def load_user_data_from_export(export_path: Path, user_substr: str) -> tuple[str, bytes]:
    for line in export_path.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("#") or line.startswith("Login\t"):
            continue
        if user_substr.lower() not in line.lower():
            continue
        parts = line.split("\t")
        # Login DisplayName Email Department OSName UserIdHex PasswordDataHex
        if len(parts) < 7:
            continue
        return parts[0], bytes.fromhex(parts[6])
    raise SystemExit(f"User {user_substr!r} not found in export")


def load_user_data_from_sql(server: str, database: str, user_substr: str) -> tuple[str, bytes]:
    import pyodbc

    conn = pyodbc.connect(
        f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER={server};DATABASE={database};"
        "Trusted_Connection=yes;Encrypt=no;TrustServerCertificate=yes;",
        autocommit=True,
    )
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
        cur.execute(
            """
            SELECT Name, Data
            FROM dbo.v8users
            WHERE Name LIKE ? OR Descr LIKE ?
            """,
            (f"%{user_substr}%", f"%{user_substr}%"),
        )
        row = cur.fetchone()
        if not row:
            raise SystemExit(f"User {user_substr!r} not found in SQL")
        return row.Name, bytes(row.Data)
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify 1C password against v8users.Data")
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--export", type=Path, default=None)
    parser.add_argument("--sql", action="store_true", help="Read Data directly from SQL Server")
    parser.add_argument("--server", default="ii1")
    parser.add_argument("--database", default="erp_pm")
    args = parser.parse_args(argv)

    if args.sql:
        login, data = load_user_data_from_sql(args.server, args.database, args.user)
    else:
        export = (
            args.export
            or Path(__file__).resolve().parent / "exports" / "erp_pm_users_export.txt"
        )
        login, data = load_user_data_from_export(export, args.user)

    print(f"User: {login}")
    print(f"Data size: {len(data)} bytes")
    print(f"Password candidate: {args.password}")

    result = verify_password_details(data, args.password)
    print(f"Key size: {result['key_size']}")
    print(f"Decoded structure length: {result['structure_len']}")
    print(f"Structure preview: {result['structure_preview'][:200]}")
    print(f"Stored hash:       {result['pass_hash']}")
    print(f"Stored hash UPPER: {result['pass_hash_upper']}")
    print(f"Candidate SHA1:    {result['expected']}")
    print(f"Candidate UPPER:   {result['expected_upper']}")
    print()

    if result["match"]:
        detail = []
        if result["match_plain"]:
            detail.append("plain")
        if result["match_upper"]:
            detail.append("UPPER")
        print(f"MATCH: YES ({', '.join(detail)})")
        return 0

    print("MATCH: NO")
    return 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
