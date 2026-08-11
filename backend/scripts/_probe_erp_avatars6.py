"""Targeted search for register 'Фотографии физических лиц'."""

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
        if head.startswith(sig) or sig in raw[:4096]:
            return name
    return f"other:{head[:20].hex()}"


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    # Classic shape: person RRef + photo ValueStorage varbinary (+ maybe tiny flags)
    cur.execute(
        """
        SELECT t.TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES t
        WHERE t.TABLE_SCHEMA='dbo'
          AND t.TABLE_TYPE='BASE TABLE'
          AND t.TABLE_NAME LIKE '_InfoRg%'
          AND t.TABLE_NAME NOT LIKE '%_VT%'
        """
    )
    tables = [r.TABLE_NAME for r in cur.fetchall()]
    print("InfoRg tables:", len(tables))

    candidates = []
    for table in tables:
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
            ORDER BY ORDINAL_POSITION
            """,
            table,
        )
        cols = cur.fetchall()
        rrefs = [c.COLUMN_NAME for c in cols if c.COLUMN_NAME.endswith("RRef") and not c.COLUMN_NAME.endswith("RRRef")]
        rrrefs = [c.COLUMN_NAME for c in cols if c.COLUMN_NAME.endswith("RRRef")]
        bins = [
            c.COLUMN_NAME
            for c in cols
            if c.DATA_TYPE in ("varbinary", "image")
            and (c.CHARACTER_MAXIMUM_LENGTH is None or c.CHARACTER_MAXIMUM_LENGTH < 0 or c.CHARACTER_MAXIMUM_LENGTH > 100)
        ]
        # Photo register is usually: 1 person ref + 1 storage, few columns
        if len(cols) <= 8 and bins and (len(rrefs) + len(rrrefs)) <= 2:
            candidates.append((table, [c.COLUMN_NAME for c in cols], rrefs or rrrefs, bins))

    print("compact InfoRg candidates:", len(candidates))
    for table, all_cols, refs, bins in candidates:
        ref = refs[0] if refs else None
        bcol = bins[0]
        try:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS Cnt,
                    SUM(CASE WHEN [{bcol}] IS NOT NULL AND DATALENGTH([{bcol}]) > 200 THEN 1 ELSE 0 END) AS WithBin,
                    MAX(DATALENGTH([{bcol}])) AS MaxLen
                FROM dbo.[{table}] WITH (NOLOCK)
                """
            )
            stats = cur.fetchone()
        except Exception as exc:  # noqa: BLE001
            print(table, "stats error", exc)
            continue
        if not stats.WithBin:
            continue
        cur.execute(
            f"""
            SELECT TOP 1 [{bcol}] AS Bin
            FROM dbo.[{table}] WITH (NOLOCK)
            WHERE [{bcol}] IS NOT NULL AND DATALENGTH([{bcol}]) > 200
            ORDER BY DATALENGTH([{bcol}]) DESC
            """
        )
        sample = cur.fetchone()
        kind = magic(sample.Bin if sample else None)
        print(
            f"{table}\tcols={all_cols}\trows={stats.Cnt}\twith_bin={stats.WithBin}\t"
            f"max={stats.MaxLen}\t{kind}"
        )

        # If looks like image or 1C storage of image-size, try join to person
        if ref and stats.MaxLen and stats.MaxLen > 1000:
            try:
                cur.execute(
                    f"""
                    SELECT TOP 5
                        CAST(p._Description AS nvarchar(256)) AS Fio,
                        DATALENGTH(t.[{bcol}]) AS Len
                    FROM dbo.[{table}] t WITH (NOLOCK)
                    INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                        ON t.[{ref}] = p._IDRRef
                    WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 200
                    ORDER BY DATALENGTH(t.[{bcol}]) DESC
                    """
                )
                people = cur.fetchall()
                if people:
                    print("  linked persons:", [(x.Fio, x.Len) for x in people])
            except Exception:
                # maybe composite RRRef
                pass
            if ref.endswith("RRRef"):
                try:
                    cur.execute(
                        f"""
                        SELECT TOP 5
                            CAST(p._Description AS nvarchar(256)) AS Fio,
                            DATALENGTH(t.[{bcol}]) AS Len
                        FROM dbo.[{table}] t WITH (NOLOCK)
                        INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                            ON t.[{ref}] = p._IDRRef
                        WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 200
                        ORDER BY DATALENGTH(t.[{bcol}]) DESC
                        """
                    )
                    people = cur.fetchall()
                    if people:
                        print("  linked persons via RRRef:", [(x.Fio, x.Len) for x in people])
                except Exception as exc:  # noqa: BLE001
                    print("  join fail", exc)

    # Also try: any InfoRg joinable to person with binary > 1KB
    print("\n=== Broader: InfoRg with RRef joinable to person and binary>1KB ===")
    cur.execute(
        """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo'
          AND TABLE_NAME LIKE '_InfoRg%'
          AND (
            COLUMN_NAME LIKE '%RRef'
          )
        """
    )
    # Too many — instead use known standard: search tables where join to 596 yields rows AND has varbinary
    cur.execute(
        """
        SELECT c.TABLE_NAME
        FROM INFORMATION_SCHEMA.COLUMNS c
        WHERE c.TABLE_SCHEMA='dbo'
          AND c.TABLE_NAME LIKE '_InfoRg%'
          AND c.DATA_TYPE IN ('varbinary','image')
        GROUP BY c.TABLE_NAME
        """
    )
    bin_tables = [r.TABLE_NAME for r in cur.fetchall()]
    found_person_photos = []
    for table in bin_tables:
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME=?
            """,
            table,
        )
        cols = cur.fetchall()
        ref_cols = [
            c.COLUMN_NAME
            for c in cols
            if c.COLUMN_NAME.endswith("RRef") or c.COLUMN_NAME.endswith("RRRef")
        ]
        bin_cols = [c.COLUMN_NAME for c in cols if c.DATA_TYPE in ("varbinary", "image")]
        for ref in ref_cols:
            for bcol in bin_cols:
                try:
                    cur.execute(
                        f"""
                        SELECT TOP 3
                            CAST(p._Description AS nvarchar(256)) AS Fio,
                            DATALENGTH(t.[{bcol}]) AS Len
                        FROM dbo.[{table}] t WITH (NOLOCK)
                        INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                            ON t.[{ref}] = p._IDRRef
                        WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 1000
                        ORDER BY DATALENGTH(t.[{bcol}]) DESC
                        """
                    )
                    rows = cur.fetchall()
                except Exception:
                    continue
                if rows:
                    cur.execute(
                        f"""
                        SELECT TOP 1 t.[{bcol}] AS Bin
                        FROM dbo.[{table}] t WITH (NOLOCK)
                        INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                            ON t.[{ref}] = p._IDRRef
                        WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 1000
                        ORDER BY DATALENGTH(t.[{bcol}]) DESC
                        """
                    )
                    sample = cur.fetchone()
                    kind = magic(sample.Bin if sample else None)
                    item = (table, ref, bcol, [(r.Fio, r.Len) for r in rows], kind)
                    found_person_photos.append(item)
                    print("FOUND", item[0], item[1], item[2], item[3], item[4])
                    break
            else:
                continue
            break

    print("\nTotal person-linked binary InfoRg hits:", len(found_person_photos))

    # Volume / file storage path fields for photos
    print("\n=== Count persons vs photo-register-like row totals if found ===")
    cur.execute("SELECT COUNT(*) AS Cnt FROM dbo._Reference596 WITH (NOLOCK) WHERE _Folder = 0x00")
    print("persons:", cur.fetchone().Cnt)

    conn.close()


if __name__ == "__main__":
    main()
