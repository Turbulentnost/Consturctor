"""Probe erp_pm for user photo / avatar storage."""

from __future__ import annotations

import pyodbc

from app.config import settings


def connect() -> pyodbc.Connection:
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
    return pyodbc.connect(";".join(parts) + ";", autocommit=True)


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    print("=== Columns matching photo/image/picture/avatar/binary ===")
    cur.execute(
        """
        SELECT TOP 300 c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE
            c.COLUMN_NAME LIKE '%Photo%'
            OR c.COLUMN_NAME LIKE '%photo%'
            OR c.COLUMN_NAME LIKE '%Image%'
            OR c.COLUMN_NAME LIKE '%image%'
            OR c.COLUMN_NAME LIKE '%Picture%'
            OR c.COLUMN_NAME LIKE '%picture%'
            OR c.COLUMN_NAME LIKE '%Avatar%'
            OR c.COLUMN_NAME LIKE '%avatar%'
            OR c.COLUMN_NAME LIKE '%Foto%'
            OR c.COLUMN_NAME LIKE '%foto%'
            OR c.COLUMN_NAME LIKE '%BinaryData%'
            OR c.COLUMN_NAME LIKE '%Storage%'
        ORDER BY c.TABLE_NAME, c.COLUMN_NAME
        """
    )
    rows = cur.fetchall()
    print(f"count={len(rows)}")
    for r in rows[:150]:
        print(f"{r.TABLE_NAME}\t{r.COLUMN_NAME}\t{r.DATA_TYPE}\t{r.CHARACTER_MAXIMUM_LENGTH}")

    print("\n=== Binary columns on employee/person refs ===")
    for table in ("_Reference366", "_Reference596", "v8users"):
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = ?
              AND DATA_TYPE IN ('varbinary', 'image', 'binary')
            ORDER BY ORDINAL_POSITION
            """,
            table,
        )
        found = cur.fetchall()
        print(f"TABLE {table}: {len(found)} binary cols")
        for r in found:
            print(f"  {r.COLUMN_NAME}\t{r.DATA_TYPE}\t{r.CHARACTER_MAXIMUM_LENGTH}")

    print("\n=== Tables with photo/image/binary/storage in name ===")
    cur.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND (
            TABLE_NAME LIKE '%Photo%'
            OR TABLE_NAME LIKE '%photo%'
            OR TABLE_NAME LIKE '%Image%'
            OR TABLE_NAME LIKE '%Picture%'
            OR TABLE_NAME LIKE '%Foto%'
            OR TABLE_NAME LIKE '%BinaryData%'
            OR TABLE_NAME LIKE '%Storage%'
            OR TABLE_NAME LIKE '%AttachedFile%'
            OR TABLE_NAME LIKE '%FileStorage%'
          )
        ORDER BY TABLE_NAME
        """
    )
    tables = [r.TABLE_NAME for r in cur.fetchall()]
    print(f"count={len(tables)}")
    for name in tables[:200]:
        print(name)

    # Common 1C pattern: person photo as attached files / binary storage refs
    print("\n=== Sample: any non-null binary on _Reference596? ===")
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = '_Reference596'
        ORDER BY ORDINAL_POSITION
        """
    )
    cols = cur.fetchall()
    print(f"_Reference596 columns: {len(cols)}")
    for r in cols:
        if r.DATA_TYPE in ("varbinary", "image", "binary") or any(
            x in r.COLUMN_NAME.lower() for x in ("photo", "image", "picture", "foto", "file", "storage")
        ):
            print(f"  interesting: {r.COLUMN_NAME}\t{r.DATA_TYPE}")

    conn.close()


if __name__ == "__main__":
    main()
