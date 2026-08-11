"""Find any SQL rows that look like physical-person photos."""

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
        "Trusted_Connection=yes",
    ]
    return pyodbc.connect(";".join(parts) + ";", autocommit=True)


def magic(data: bytes | None) -> str:
    if not data:
        return "empty"
    raw = bytes(data)
    for sig, name in (
        (b"\xff\xd8\xff", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"GIF8", "gif"),
        (b"BM", "bmp"),
    ):
        if raw.startswith(sig) or sig in raw[:8192]:
            return name
    return f"other:{raw[:16].hex()}"


def main() -> None:
    print("connecting", flush=True)
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    # 1) InfoRg with ANY column joinable to person + any varbinary > 1KB
    cur.execute(
        """
        SELECT t.name AS TableName
        FROM sys.tables t
        WHERE t.name LIKE '\\_InfoRg%' ESCAPE '\\'
          AND t.name NOT LIKE '%\\_VT%' ESCAPE '\\'
          AND t.name NOT LIKE '%ChngR%'
          AND EXISTS (
              SELECT 1
              FROM sys.columns c
              INNER JOIN sys.types ty ON c.user_type_id = ty.user_type_id
              WHERE c.object_id = t.object_id
                AND ty.name IN ('varbinary', 'image')
          )
        """
    )
    tables = [r.TableName for r in cur.fetchall()]
    print(f"InfoRg with varbinary: {len(tables)}", flush=True)

    found = []
    for idx, table in enumerate(tables, 1):
        cur.execute(
            """
            SELECT c.name, ty.name AS type_name
            FROM sys.columns c
            INNER JOIN sys.types ty ON c.user_type_id = ty.user_type_id
            WHERE c.object_id = OBJECT_ID(?)
            """,
            f"dbo.{table}",
        )
        cols = cur.fetchall()
        refs = [c.name for c in cols if c.name.endswith("RRef") or c.name.endswith("RRRef")]
        bins = [c.name for c in cols if c.type_name in ("varbinary", "image")]
        for ref in refs:
            matched = False
            for bcol in bins:
                try:
                    cur.execute(
                        f"""
                        SELECT TOP 1
                            CAST(p._Description AS nvarchar(256)) AS Fio,
                            DATALENGTH(t.[{bcol}]) AS Len,
                            t.[{bcol}] AS Bin
                        FROM dbo.[{table}] t WITH (NOLOCK)
                        INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                            ON t.[{ref}] = p._IDRRef
                        WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 1000
                        ORDER BY DATALENGTH(t.[{bcol}]) DESC
                        """
                    )
                    row = cur.fetchone()
                except Exception:
                    continue
                if row:
                    kind = magic(row.Bin)
                    item = (table, ref, bcol, row.Fio, int(row.Len), kind)
                    found.append(item)
                    print("FOUND", item, flush=True)
                    matched = True
                    break
            if matched:
                break
        if idx % 50 == 0:
            print(f"progress {idx}/{len(tables)} found={len(found)}", flush=True)

    print(f"\nInfoRg person+binary hits: {len(found)}", flush=True)

    # 2) Reference catalogs (attached files) joinable to person with large binary
    print("\nScanning _Reference* with varbinary for person links...", flush=True)
    cur.execute(
        """
        SELECT t.name AS TableName
        FROM sys.tables t
        WHERE t.name LIKE '\\_Reference%' ESCAPE '\\'
          AND t.name NOT LIKE '%\\_VT%' ESCAPE '\\'
          AND t.name NOT LIKE '%ChngR%'
          AND EXISTS (
              SELECT 1
              FROM sys.columns c
              INNER JOIN sys.types ty ON c.user_type_id = ty.user_type_id
              WHERE c.object_id = t.object_id
                AND ty.name IN ('varbinary', 'image')
                AND (c.max_length < 0 OR c.max_length > 200)
          )
        """
    )
    refs_tables = [r.TableName for r in cur.fetchall()]
    print(f"Reference tables with large varbinary: {len(refs_tables)}", flush=True)
    ref_found = []
    for idx, table in enumerate(refs_tables, 1):
        if table in ("_Reference366", "_Reference596"):
            continue
        cur.execute(
            """
            SELECT c.name, ty.name AS type_name, c.max_length
            FROM sys.columns c
            INNER JOIN sys.types ty ON c.user_type_id = ty.user_type_id
            WHERE c.object_id = OBJECT_ID(?)
            """,
            f"dbo.{table}",
        )
        cols = cur.fetchall()
        refs = [c.name for c in cols if c.name.endswith("RRef") or c.name.endswith("RRRef")]
        bins = [
            c.name
            for c in cols
            if c.type_name in ("varbinary", "image") and (c.max_length is None or c.max_length < 0 or c.max_length > 200)
        ]
        for ref in refs:
            matched = False
            for bcol in bins:
                try:
                    cur.execute(
                        f"""
                        SELECT TOP 1
                            CAST(p._Description AS nvarchar(256)) AS Fio,
                            CAST(t._Description AS nvarchar(256)) AS FileName,
                            DATALENGTH(t.[{bcol}]) AS Len,
                            t.[{bcol}] AS Bin
                        FROM dbo.[{table}] t WITH (NOLOCK)
                        INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                            ON t.[{ref}] = p._IDRRef
                        WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 1000
                        ORDER BY DATALENGTH(t.[{bcol}]) DESC
                        """
                    )
                    row = cur.fetchone()
                except Exception:
                    continue
                if row:
                    kind = magic(row.Bin)
                    item = (table, ref, bcol, row.Fio, getattr(row, "FileName", None), int(row.Len), kind)
                    ref_found.append(item)
                    print("REF_FOUND", item, flush=True)
                    matched = True
                    break
            if matched:
                break
        if idx % 40 == 0:
            print(f"ref progress {idx}/{len(refs_tables)} found={len(ref_found)}", flush=True)

    print(f"\nReference person+binary hits: {len(ref_found)}", flush=True)

    # 3) File names suggesting person photos in descriptions near person owners
    print("\nLooking for jpg/png descriptions owned by persons...", flush=True)
    cur.execute(
        """
        SELECT t.name AS TableName
        FROM sys.tables t
        WHERE t.name LIKE '\\_Reference%' ESCAPE '\\'
          AND t.name NOT LIKE '%\\_VT%' ESCAPE '\\'
          AND EXISTS (
              SELECT 1 FROM sys.columns c WHERE c.object_id=t.object_id AND c.name='_Description'
          )
        """
    )
    desc_tables = [r.TableName for r in cur.fetchall()]
    img_name_hits = 0
    for table in desc_tables:
        cur.execute(
            """
            SELECT c.name
            FROM sys.columns c
            WHERE c.object_id = OBJECT_ID(?)
              AND (c.name LIKE '%RRef' OR c.name LIKE '%RRRef')
            """,
            f"dbo.{table}",
        )
        refs = [r.name for r in cur.fetchall()]
        for ref in refs:
            try:
                cur.execute(
                    f"""
                    SELECT TOP 1
                        CAST(p._Description AS nvarchar(256)) AS Fio,
                        CAST(t._Description AS nvarchar(256)) AS FileName
                    FROM dbo.[{table}] t WITH (NOLOCK)
                    INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                        ON t.[{ref}] = p._IDRRef
                    WHERE
                        LOWER(CAST(t._Description AS nvarchar(256))) LIKE '%.jpg'
                        OR LOWER(CAST(t._Description AS nvarchar(256))) LIKE '%.jpeg'
                        OR LOWER(CAST(t._Description AS nvarchar(256))) LIKE '%.png'
                    """
                )
                row = cur.fetchone()
            except Exception:
                continue
            if row:
                img_name_hits += 1
                print("NAME_HIT", table, ref, row.Fio, row.FileName, flush=True)
                break
    print(f"tables with person-owned image filenames: {img_name_hits}", flush=True)

    conn.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
