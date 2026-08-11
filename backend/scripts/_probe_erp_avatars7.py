"""Quick check: does ERP store physical-person photos with usable image bytes?"""

from __future__ import annotations

import sys

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
    return f"other:{raw[:24].hex()}"


def main() -> None:
    print("connecting", flush=True)
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    print("metadata presence:", flush=True)
    cur.execute(
        """
        SELECT TOP 5 CAST(_Description AS nvarchar(400)) AS Descr
        FROM dbo._Reference194X1 WITH (NOLOCK)
        WHERE CAST(_Description AS nvarchar(400)) LIKE N'%Фотографии физических лиц%'
        """
    )
    for r in cur.fetchall():
        print(" ", r.Descr, flush=True)

    # Compact InfoRg candidates via sys.columns (faster than INFORMATION_SCHEMA loops)
    print("loading compact InfoRg candidates...", flush=True)
    cur.execute(
        """
        SELECT t.name AS TableName
        FROM sys.tables t
        WHERE t.name LIKE '\\_InfoRg%' ESCAPE '\\'
          AND t.name NOT LIKE '%\\_VT%' ESCAPE '\\'
          AND t.name NOT LIKE '%ChngR%'
        """
    )
    tables = [r.TableName for r in cur.fetchall()]
    print(f"InfoRg tables: {len(tables)}", flush=True)

    hits = []
    for i, table in enumerate(tables, 1):
        cur.execute(
            """
            SELECT c.name, ty.name AS type_name, c.max_length, c.column_id
            FROM sys.columns c
            INNER JOIN sys.types ty ON c.user_type_id = ty.user_type_id
            WHERE c.object_id = OBJECT_ID(?)
            ORDER BY c.column_id
            """,
            f"dbo.{table}",
        )
        cols = cur.fetchall()
        if not cols or len(cols) > 8:
            continue
        names = [c.name for c in cols]
        bin_cols = [c.name for c in cols if c.type_name in ("varbinary", "image") and (c.max_length < 0 or c.max_length > 100)]
        ref_cols = [c.name for c in cols if c.name.endswith("RRef") or c.name.endswith("RRRef")]
        if not bin_cols or not ref_cols:
            continue
        bcol = bin_cols[0]
        ref = ref_cols[0]
        cur.execute(
            f"""
            SELECT
                COUNT_BIG(*) AS Cnt,
                SUM(CASE WHEN [{bcol}] IS NOT NULL AND DATALENGTH([{bcol}]) > 500 THEN 1 ELSE 0 END) AS WithBin,
                MAX(DATALENGTH([{bcol}])) AS MaxLen
            FROM dbo.[{table}] WITH (NOLOCK)
            """
        )
        stats = cur.fetchone()
        if not stats.WithBin:
            continue
        cur.execute(
            f"""
            SELECT TOP 1 [{bcol}] AS Bin
            FROM dbo.[{table}] WITH (NOLOCK)
            WHERE [{bcol}] IS NOT NULL AND DATALENGTH([{bcol}]) > 500
            ORDER BY DATALENGTH([{bcol}]) DESC
            """
        )
        sample = cur.fetchone()
        kind = magic(sample.Bin if sample else None)
        people = []
        try:
            cur.execute(
                f"""
                SELECT TOP 5
                    CAST(p._Description AS nvarchar(256)) AS Fio,
                    DATALENGTH(t.[{bcol}]) AS Len
                FROM dbo.[{table}] t WITH (NOLOCK)
                INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                    ON t.[{ref}] = p._IDRRef
                WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 500
                ORDER BY DATALENGTH(t.[{bcol}]) DESC
                """
            )
            people = [(r.Fio, int(r.Len)) for r in cur.fetchall()]
        except Exception:
            people = []
        row = {
            "table": table,
            "ref": ref,
            "bin": bcol,
            "rows": int(stats.Cnt),
            "with_bin": int(stats.WithBin),
            "max": int(stats.MaxLen or 0),
            "kind": kind,
            "people": people,
        }
        hits.append(row)
        print("CAND", row, flush=True)
        if i % 200 == 0:
            print(f"progress {i}/{len(tables)}", flush=True)

    print("\n=== Summary ===", flush=True)
    person_linked = [h for h in hits if h["people"]]
    image_like = [h for h in hits if h["kind"] in {"jpeg", "png", "gif", "bmp"} or "jpeg" in h["kind"] or "png" in h["kind"]]
    print(f"compact binary InfoRg with data: {len(hits)}", flush=True)
    print(f"linked to _Reference596 (persons): {len(person_linked)}", flush=True)
    print(f"raw image signatures: {len(image_like)}", flush=True)
    for h in person_linked:
        print("PERSON_PHOTO", h, flush=True)
    for h in image_like:
        print("IMAGE", h, flush=True)

    # Employee/person direct fields already known tiny; confirm zero large binaries
    cur.execute(
        """
        SELECT
            SUM(CASE WHEN DATALENGTH(_Fld11003) > 1000 THEN 1 ELSE 0 END) AS Big11003,
            SUM(CASE WHEN DATALENGTH(_Fld129493) > 1000 THEN 1 ELSE 0 END) AS Big129493
        FROM dbo._Reference366 WITH (NOLOCK)
        """
    )
    r = cur.fetchone()
    print(f"employee large binaries: _Fld11003={r.Big11003}, _Fld129493={r.Big129493}", flush=True)

    conn.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
    sys.exit(0)
