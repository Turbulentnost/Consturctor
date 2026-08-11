"""Deeper search for person/employee photos in erp_pm."""

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


def magic(data: bytes | None) -> str:
    if not data:
        return "empty"
    head = bytes(data[:64])
    for sig, name in (
        (b"\xff\xd8\xff", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"GIF8", "gif"),
        (b"BM", "bmp"),
    ):
        if sig in head or sig in bytes(data[:4096]):
            return name
    return f"other:{head[:12].hex()}"


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    # Find tables that have both a Description-like text and a large varbinary column
    print("=== Tables with large varbinary columns (possible file/photo storage) ===")
    cur.execute(
        """
        SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA = 'dbo'
          AND c.DATA_TYPE IN ('varbinary', 'image')
          AND (c.CHARACTER_MAXIMUM_LENGTH IS NULL OR c.CHARACTER_MAXIMUM_LENGTH = -1 OR c.CHARACTER_MAXIMUM_LENGTH > 1000)
          AND c.TABLE_NAME LIKE '_Reference%'
          AND c.TABLE_NAME NOT LIKE '%_VT%'
        ORDER BY c.TABLE_NAME, c.COLUMN_NAME
        """
    )
    candidates = cur.fetchall()
    print(f"candidate cols={len(candidates)}")
    # Sample occupancy for promising ones: skip tiny UUID-like only if we can measure quickly
    checked = 0
    photoish = []
    for r in candidates:
        table, col = r.TABLE_NAME, r.COLUMN_NAME
        # Skip known system-ish if too many; probe max length
        try:
            cur.execute(
                f"""
                SELECT TOP 1
                    DATALENGTH([{col}]) AS Len,
                    [{col}] AS Bin
                FROM dbo.[{table}] WITH (NOLOCK)
                WHERE [{col}] IS NOT NULL AND DATALENGTH([{col}]) > 1000
                ORDER BY DATALENGTH([{col}]) DESC
                """
            )
            row = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            print(f"skip {table}.{col}: {exc}")
            continue
        checked += 1
        if not row:
            continue
        kind = magic(row.Bin)
        print(f"{table}.{col}\tmax_sample_len={row.Len}\t{kind}")
        if kind in {"jpeg", "png", "gif", "bmp"} or "jpeg" in kind or "png" in kind:
            photoish.append((table, col, row.Len, kind))
        if checked >= 80:
            print("... stopped after 80 probes")
            break

    print("\n=== Photo-like columns found ===")
    for item in photoish:
        print(item)

    # Inspect Files content for images
    print("\n=== Sample Files.BinaryData magic ===")
    cur.execute(
        """
        SELECT TOP 20 FileName, DataSize, BinaryData
        FROM dbo.Files WITH (NOLOCK)
        WHERE BinaryData IS NOT NULL
        ORDER BY DataSize DESC
        """
    )
    img_files = 0
    for r in cur.fetchall():
        kind = magic(r.BinaryData)
        if kind in {"jpeg", "png", "gif", "bmp"} or "jpeg" in kind or "png" in kind:
            img_files += 1
        print(f"{r.FileName}\tsize={r.DataSize}\t{kind}")
    print("image-like among top20:", img_files)

    # Search BinaryData chunks for image signatures (expensive) - sample large chunks
    print("\n=== Sample BinaryData.f_data magic (top sizes) ===")
    cur.execute(
        """
        SELECT TOP 15 f_key, f_off, f_num, DATALENGTH(f_data) AS Len, f_data
        FROM dbo.BinaryData WITH (NOLOCK)
        WHERE f_data IS NOT NULL
        ORDER BY DATALENGTH(f_data) DESC
        """
    )
    for r in cur.fetchall():
        print(f"key={r.f_key.hex()} off={r.f_off} num={r.f_num} len={r.Len} {magic(r.f_data)}")

    # Person attached files: common pattern Owner = person, Extension column
    print("\n=== Refs with Extension + Size + Owner-like columns ===")
    cur.execute(
        """
        SELECT t.TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES t
        WHERE t.TABLE_TYPE = 'BASE TABLE'
          AND t.TABLE_NAME LIKE '_Reference%'
          AND t.TABLE_NAME NOT LIKE '%_VT%'
          AND EXISTS (
              SELECT 1 FROM INFORMATION_SCHEMA.COLUMNS c
              WHERE c.TABLE_NAME = t.TABLE_NAME AND c.COLUMN_NAME LIKE '%Extension%'
          )
        ORDER BY t.TABLE_NAME
        """
    )
    ext_tables = [r.TABLE_NAME for r in cur.fetchall()]
    print("tables with Extension col:", len(ext_tables))
    for name in ext_tables[:40]:
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
            """,
            name,
        )
        cols = [f"{c.COLUMN_NAME}:{c.DATA_TYPE}" for c in cur.fetchall()]
        print(name, "=>", ", ".join(cols[:25]))

    conn.close()


if __name__ == "__main__":
    main()
