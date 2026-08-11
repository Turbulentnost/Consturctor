"""Check whether employee varbinary fields / BinaryData hold photos."""

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
    return pyodbc.connect(";'.join(parts) + ';", autocommit=True) if False else pyodbc.connect(
        ";".join(parts) + ";", autocommit=True
    )


def magic(data: bytes | None) -> str:
    if not data:
        return "empty"
    head = data[:16]
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if head.startswith(b"BM"):
        return "bmp"
    if head.startswith(b"RIFF") and b"WEBP" in data[:16]:
        return "webp"
    # 1C ValueStorage often has a wrapper; look for embedded image signatures
    for sig, name in (
        (b"\xff\xd8\xff", "jpeg-embedded"),
        (b"\x89PNG\r\n\x1a\n", "png-embedded"),
        (b"GIF8", "gif-embedded"),
    ):
        if sig in data[:512] or sig in data[:4096]:
            return name
    return f"unknown head={head.hex()}"


def main() -> None:
    conn = connect()
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

    print("=== _Reference366 varbinary field occupancy ===")
    cur.execute(
        """
        SELECT
            COUNT(*) AS Total,
            SUM(CASE WHEN _Fld11003 IS NOT NULL AND DATALENGTH(_Fld11003) > 0 THEN 1 ELSE 0 END) AS Fld11003Filled,
            SUM(CASE WHEN _Fld129493 IS NOT NULL AND DATALENGTH(_Fld129493) > 0 THEN 1 ELSE 0 END) AS Fld129493Filled,
            MAX(DATALENGTH(_Fld11003)) AS Max11003,
            MAX(DATALENGTH(_Fld129493)) AS Max129493,
            AVG(CAST(DATALENGTH(_Fld11003) AS bigint)) AS Avg11003,
            AVG(CAST(DATALENGTH(_Fld129493) AS bigint)) AS Avg129493
        FROM dbo._Reference366 WITH (NOLOCK)
        """
    )
    row = cur.fetchone()
    print(
        f"total={row.Total} filled_11003={row.Fld11003Filled} filled_129493={row.Fld129493Filled} "
        f"max_11003={row.Max11003} max_129493={row.Max129493} avg_11003={row.Avg11003} avg_129493={row.Avg129493}"
    )

    print("\n=== Sample filled _Fld11003 / _Fld129493 ===")
    cur.execute(
        """
        SELECT TOP 10
            CAST(_Description AS nvarchar(256)) AS Fio,
            DATALENGTH(_Fld11003) AS Len11003,
            DATALENGTH(_Fld129493) AS Len129493,
            _Fld11003 AS Bin11003,
            _Fld129493 AS Bin129493
        FROM dbo._Reference366 WITH (NOLOCK)
        WHERE (DATALENGTH(_Fld11003) > 0 OR DATALENGTH(_Fld129493) > 0)
        ORDER BY COALESCE(DATALENGTH(_Fld11003), 0) + COALESCE(DATALENGTH(_Fld129493), 0) DESC
        """
    )
    for r in cur.fetchall():
        b1 = bytes(r.Bin11003) if r.Bin11003 else b""
        b2 = bytes(r.Bin129493) if r.Bin129493 else b""
        print(
            f"{r.Fio!r}\tlen11003={r.Len11003}\t{magic(b1)}\t"
            f"len129493={r.Len129493}\t{magic(b2)}"
        )

    print("\n=== BinaryData table shape ===")
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'BinaryData'
        ORDER BY ORDINAL_POSITION
        """
    )
    for r in cur.fetchall():
        print(f"  {r.COLUMN_NAME}\t{r.DATA_TYPE}\t{r.CHARACTER_MAXIMUM_LENGTH}")

    cur.execute("SELECT COUNT(*) AS Cnt FROM dbo.BinaryData WITH (NOLOCK)")
    print("BinaryData rows:", cur.fetchone().Cnt)

    print("\n=== Files table occupancy ===")
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'Files'
        ORDER BY ORDINAL_POSITION
        """
    )
    for r in cur.fetchall():
        print(f"  {r.COLUMN_NAME}\t{r.DATA_TYPE}\t{r.CHARACTER_MAXIMUM_LENGTH}")
    cur.execute(
        """
        SELECT COUNT(*) AS Cnt,
               SUM(CASE WHEN BinaryData IS NOT NULL AND DATALENGTH(BinaryData) > 0 THEN 1 ELSE 0 END) AS Filled,
               MAX(DATALENGTH(BinaryData)) AS MaxLen
        FROM dbo.Files WITH (NOLOCK)
        """
    )
    r = cur.fetchone()
    print(f"Files rows={r.Cnt} filled={r.Filled} max={r.MaxLen}")

    # Look for attached-file catalogs referencing persons/employees
    print("\n=== Candidate attached-file / photo catalogs ===")
    cur.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND (
            TABLE_NAME LIKE '_Reference%Attached%'
            OR TABLE_NAME LIKE '_Reference%File%'
            OR TABLE_NAME LIKE '_InfoRg%File%'
            OR TABLE_NAME LIKE '%Фото%'
          )
        ORDER BY TABLE_NAME
        """
    )
    names = [x.TABLE_NAME for x in cur.fetchall()]
    print("count=", len(names))
    for n in names[:100]:
        print(n)

    # Search field synonyms in config metadata if available via Config table is huge;
    # instead inspect description columns around employee photo-like refs.
    print("\n=== Look for fields containing 'фото'/'изображ' in known description tables ===")
    cur.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_TYPE = 'BASE TABLE'
          AND TABLE_NAME LIKE '_Reference%VT%'
          AND TABLE_NAME LIKE '%366%'
        ORDER BY TABLE_NAME
        """
    )
    print("Employee VT tables:")
    for r in cur.fetchall()[:50]:
        print(" ", r.TABLE_NAME)

    conn.close()


if __name__ == "__main__":
    main()
