"""Locate physical-person photo register and check if photos exist for users."""

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
    raw = bytes(data)
    head = raw[:64]
    for sig, name in (
        (b"\xff\xd8\xff", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"GIF8", "gif"),
        (b"BM", "bmp"),
    ):
        if head.startswith(sig) or sig in head or sig in raw[:4096]:
            return name
    if head.startswith(b"STOREHDR") or head[:4] == b"\x01\x01\x00\x00" or head[:2] == b"\x01\x01":
        return f"1c-storage:{head[:16].hex()}"
    return f"other:{head[:16].hex()}"


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    print("=== Metadata hints for person photos ===")
    cur.execute(
        """
        SELECT TOP 20
            CAST(_Description AS nvarchar(512)) AS Descr,
            CONVERT(varchar(34), _IDRRef, 1) AS IdHex
        FROM dbo._Reference194X1 WITH (NOLOCK)
        WHERE CAST(_Description AS nvarchar(512)) LIKE N'%Фотограф%физич%'
           OR CAST(_Description AS nvarchar(512)) LIKE N'%Фотографии физических%'
        """
    )
    for r in cur.fetchall():
        print(r.Descr, r.IdHex)

    # Find InfoRg tables that reference person (_Reference596) and have binary/storage
    print("\n=== InfoRg tables with person-like RRef + varbinary ===")
    cur.execute(
        """
        SELECT DISTINCT c.TABLE_NAME
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA='dbo'
          AND c.TABLE_NAME LIKE '_InfoRg%'
          AND c.DATA_TYPE IN ('varbinary', 'image')
        ORDER BY c.TABLE_NAME
        """
    )
    info_bin = [r.TABLE_NAME for r in cur.fetchall()]
    print("InfoRg with varbinary:", len(info_bin))
    for name in info_bin[:80]:
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME=?
            ORDER BY ORDINAL_POSITION
            """,
            name,
        )
        cols = cur.fetchall()
        print(name, "=>", ", ".join(f"{c.COLUMN_NAME}:{c.DATA_TYPE}" for c in cols))

    # Probe each InfoRg-with-varbinary for image occupancy
    print("\n=== Probe InfoRg binary fields for images ===")
    for name in info_bin:
        cur.execute(
            """
            SELECT COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME=? AND DATA_TYPE IN ('varbinary','image')
            """,
            name,
        )
        bin_cols = [r.COLUMN_NAME for r in cur.fetchall()]
        for col in bin_cols:
            try:
                cur.execute(
                    f"""
                    SELECT COUNT(*) AS Cnt,
                           MAX(DATALENGTH([{col}])) AS MaxLen
                    FROM dbo.[{name}] WITH (NOLOCK)
                    WHERE [{col}] IS NOT NULL AND DATALENGTH([{col}]) > 100
                    """
                )
                stats = cur.fetchone()
                if not stats.Cnt:
                    continue
                cur.execute(
                    f"""
                    SELECT TOP 1 [{col}] AS Bin
                    FROM dbo.[{name}] WITH (NOLOCK)
                    WHERE [{col}] IS NOT NULL AND DATALENGTH([{col}]) > 100
                    ORDER BY DATALENGTH([{col}]) DESC
                    """
                )
                sample = cur.fetchone()
                kind = magic(sample.Bin if sample else None)
                print(f"{name}.{col}\trows>{100}b={stats.Cnt}\tmax={stats.MaxLen}\t{kind}")
            except Exception as exc:  # noqa: BLE001
                print(f"{name}.{col} error: {exc}")

    # Standard register name search in Config is hard; try known ERP register numbers
    # by joining person id into InfoRg that have exactly one RRef dimension + binary
    print("\n=== Check whether person Mangasaryan appears as Owner in file catalogs ===")
    # Get person binary id
    cur.execute(
        """
        SELECT TOP 1 _IDRRef
        FROM dbo._Reference596 WITH (NOLOCK)
        WHERE _Description LIKE N'%Мангасарян%'
        """
    )
    person = cur.fetchone()
    if not person:
        print("person not found")
        conn.close()
        return
    person_id = person._IDRRef
    print("person_id", bytes(person_id).hex())

    # Find all RRef columns across InfoRg/References and count matches to this person
    # Limit to tables with 'фото' in related metadata already found: dig _Reference194 for number
    cur.execute(
        """
        SELECT TOP 50 CAST(_Description AS nvarchar(512)) AS Descr
        FROM dbo._Reference194X1 WITH (NOLOCK)
        WHERE CAST(_Description AS nvarchar(512)) LIKE N'%физических лиц%'
        """
    )
    print("\nMetadata containing 'физических лиц':")
    for r in cur.fetchall():
        print(" ", r.Descr)

    # Search ConfigCAS or similar is too heavy. Try InfoRg row counts linked by scanning
    # RRef columns equal to person id for a subset of InfoRg tables.
    cur.execute(
        """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo'
          AND TABLE_NAME LIKE '_InfoRg%'
          AND COLUMN_NAME LIKE '%RRef'
        """
    )
    rref_cols = cur.fetchall()
    print(f"\nScanning {len(rref_cols)} InfoRg RRef columns for Mangasaryan id (may take a bit)...")
    hits = []
    for r in rref_cols:
        table, col = r.TABLE_NAME, r.COLUMN_NAME
        try:
            cur.execute(
                f"SELECT TOP 1 1 AS X FROM dbo.[{table}] WITH (NOLOCK) WHERE [{col}] = ?",
                (person_id,),
            )
            if cur.fetchone():
                hits.append((table, col))
                print("HIT", table, col)
        except Exception:
            continue
    print("total hits:", len(hits))

    # For hit tables, show structure and whether binary/photo-like payload exists
    print("\n=== Structures of InfoRg tables referencing the person ===")
    seen = set()
    for table, _col in hits:
        if table in seen:
            continue
        seen.add(table)
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME=?
            ORDER BY ORDINAL_POSITION
            """,
            table,
        )
        cols = cur.fetchall()
        print(table, "=>", ", ".join(f"{c.COLUMN_NAME}:{c.DATA_TYPE}" for c in cols))
        cur.execute(f"SELECT COUNT(*) AS Cnt FROM dbo.[{table}] WITH (NOLOCK)")
        print("  rows:", cur.fetchone().Cnt)

    conn.close()


if __name__ == "__main__":
    main()
