"""Inspect person-linked InfoRg binaries for embedded images; count coverage."""

from __future__ import annotations

import zlib

import pyodbc

from app.config import settings

TARGETS = [
    ("_InfoRg43471X1", "_Fld43472_RRRef", "_Fld43474"),
    ("_InfoRg129887", "_Fld131808RRef", "_Fld129901"),
    ("_InfoRg98758", "_Fld121788RRef", "_Fld129404"),
]


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


def find_image(data: bytes) -> str:
    for sig, name in (
        (b"\xff\xd8\xff", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"GIF8", "gif"),
        (b"BM", "bmp"),
    ):
        pos = data.find(sig)
        if pos >= 0:
            return f"{name}@offset={pos}"
    # try zlib inflate variants often used around 1C storage
    for start in (0, 2, 4, 8, 16, 18, 20):
        try:
            out = zlib.decompress(data[start:])
        except Exception:
            try:
                out = zlib.decompress(data[start:], -15)
            except Exception:
                continue
        for sig, name in ((b"\xff\xd8\xff", "jpeg"), (b"\x89PNG\r\n\x1a\n", "png")):
            if sig in out[:8192] or out.find(sig) >= 0:
                return f"{name}-via-zlib@{start} out_len={len(out)}"
    return "no-image-signature"


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    cur.execute("SELECT COUNT(*) AS Cnt FROM dbo._Reference596 WITH (NOLOCK) WHERE _Folder = 0x00")
    print("persons:", cur.fetchone().Cnt, flush=True)

    for table, ref, bcol in TARGETS:
        print(f"\n=== {table} ===", flush=True)
        cur.execute(
            f"""
            SELECT
                COUNT(*) AS Cnt,
                SUM(CASE WHEN t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 0 THEN 1 ELSE 0 END) AS Filled,
                MAX(DATALENGTH(t.[{bcol}])) AS MaxLen,
                AVG(CAST(DATALENGTH(t.[{bcol}]) AS bigint)) AS AvgLen
            FROM dbo.[{table}] t WITH (NOLOCK)
            INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                ON t.[{ref}] = p._IDRRef
            """
        )
        s = cur.fetchone()
        print(f"person-linked rows={s.Cnt} filled={s.Filled} max={s.MaxLen} avg={s.AvgLen}", flush=True)

        cur.execute(
            f"""
            SELECT TOP 8
                CAST(p._Description AS nvarchar(256)) AS Fio,
                DATALENGTH(t.[{bcol}]) AS Len,
                t.[{bcol}] AS Bin
            FROM dbo.[{table}] t WITH (NOLOCK)
            INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                ON t.[{ref}] = p._IDRRef
            WHERE t.[{bcol}] IS NOT NULL AND DATALENGTH(t.[{bcol}]) > 200
            ORDER BY DATALENGTH(t.[{bcol}]) DESC
            """
        )
        for r in cur.fetchall():
            raw = bytes(r.Bin)
            print(f"  {r.Fio}\tlen={r.Len}\t{find_image(raw)}\thead={raw[:24].hex()}", flush=True)

        # Mangasaryan specifically
        cur.execute(
            f"""
            SELECT TOP 3
                CAST(p._Description AS nvarchar(256)) AS Fio,
                DATALENGTH(t.[{bcol}]) AS Len
            FROM dbo.[{table}] t WITH (NOLOCK)
            INNER JOIN dbo._Reference596 p WITH (NOLOCK)
                ON t.[{ref}] = p._IDRRef
            WHERE p._Description LIKE N'%Мангасарян%'
            """
        )
        rows = cur.fetchall()
        print("  Mangasaryan:", [(x.Fio, x.Len) for x in rows] or "none", flush=True)

    # Volume paths: tables with Path/Volume-like nvarchar and person ref
    print("\n=== Check if photos live in file volumes (path fields) ===", flush=True)
    cur.execute(
        """
        SELECT TOP 20
            CAST(_Description AS nvarchar(400)) AS Descr
        FROM dbo._Reference194X1 WITH (NOLOCK)
        WHERE CAST(_Description AS nvarchar(400)) LIKE N'%Том%файл%'
           OR CAST(_Description AS nvarchar(400)) LIKE N'%Хранилище%файл%'
           OR CAST(_Description AS nvarchar(400)) LIKE N'%Присоединенн%файл%физич%'
           OR CAST(_Description AS nvarchar(400)) LIKE N'%ФизическиеЛицаПрисоединенные%'
        """
    )
    for r in cur.fetchall():
        print(" ", r.Descr, flush=True)

    conn.close()
    print("done", flush=True)


if __name__ == "__main__":
    main()
