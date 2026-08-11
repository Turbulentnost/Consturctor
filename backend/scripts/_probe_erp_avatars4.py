"""Check if person/employee cards link to photo files; scan for image extensions."""

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

    print("=== _Reference596 all columns ===")
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='_Reference596'
        ORDER BY ORDINAL_POSITION
        """
    )
    for r in cur.fetchall():
        print(f"  {r.COLUMN_NAME}\t{r.DATA_TYPE}\t{r.CHARACTER_MAXIMUM_LENGTH}")

    print("\n=== _Reference366 all columns ===")
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME='_Reference366'
        ORDER BY ORDINAL_POSITION
        """
    )
    for r in cur.fetchall():
        print(f"  {r.COLUMN_NAME}\t{r.DATA_TYPE}\t{r.CHARACTER_MAXIMUM_LENGTH}")

    # Search nvarchar descriptions for image file names
    print("\n=== Search top refs for .jpg/.png/.jpeg in _Description ===")
    cur.execute(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA='dbo'
          AND COLUMN_NAME='_Description'
          AND TABLE_NAME LIKE '_Reference%'
          AND TABLE_NAME NOT LIKE '%_VT%'
        """
    )
    tables = [r.TABLE_NAME for r in cur.fetchall()]
    hits = []
    for table in tables:
        try:
            cur.execute(
                f"""
                SELECT TOP 3 CAST(_Description AS nvarchar(512)) AS Descr
                FROM dbo.[{table}] WITH (NOLOCK)
                WHERE
                    LOWER(CAST(_Description AS nvarchar(512))) LIKE '%.jpg'
                    OR LOWER(CAST(_Description AS nvarchar(512))) LIKE '%.jpeg'
                    OR LOWER(CAST(_Description AS nvarchar(512))) LIKE '%.png'
                    OR LOWER(CAST(_Description AS nvarchar(512))) LIKE '%.bmp'
                    OR LOWER(CAST(_Description AS nvarchar(512))) LIKE N'%фото%'
                """
            )
            rows = cur.fetchall()
        except Exception:
            continue
        if rows:
            hits.append((table, [r.Descr for r in rows]))
            print(table, "->", [r.Descr for r in rows])
    print(f"tables with image-like descriptions: {len(hits)}")

    # Count BinaryData chunks that look like jpeg/png (sample by first bytes via substring)
    print("\n=== BinaryData image signature counts (approx via LEFT) ===")
    # JPEG FF D8 FF, PNG 89 50 4E 47; also after 1C storage header (often starts 01 01 ...)
    cur.execute(
        """
        SELECT
            SUM(CASE WHEN SUBSTRING(f_data,1,3)=0xFFD8FF THEN 1 ELSE 0 END) AS JpegHead,
            SUM(CASE WHEN SUBSTRING(f_data,1,8)=0x89504E470D0A1A0A THEN 1 ELSE 0 END) AS PngHead,
            SUM(CASE WHEN SUBSTRING(f_data,1,2)=0x424D THEN 1 ELSE 0 END) AS BmpHead,
            SUM(CASE WHEN CHARINDEX(0xFFD8FF, SUBSTRING(f_data,1,64)) > 0 THEN 1 ELSE 0 END) AS JpegIn64,
            SUM(CASE WHEN CHARINDEX(0x89504E47, SUBSTRING(f_data,1,64)) > 0 THEN 1 ELSE 0 END) AS PngIn64,
            COUNT(*) AS Total
        FROM dbo.BinaryData WITH (NOLOCK)
        WHERE f_off = 0 AND f_data IS NOT NULL
        """
    )
    r = cur.fetchone()
    print(
        f"total_off0={r.Total} jpeg_head={r.JpegHead} png_head={r.PngHead} "
        f"bmp_head={r.BmpHead} jpeg_in64={r.JpegIn64} png_in64={r.PngIn64}"
    )

    # For Mangasaryan specifically - any large storage linked?
    print("\n=== Person Mangasaryan row snapshot ===")
    cur.execute(
        """
        SELECT TOP 5
            CAST(p._Description AS nvarchar(256)) AS Fio,
            CONVERT(varchar(34), p._IDRRef, 1) AS IdHex
        FROM dbo._Reference596 p WITH (NOLOCK)
        WHERE p._Description LIKE N'%Мангасарян%'
        """
    )
    for r in cur.fetchall():
        print(r.Fio, r.IdHex)

    conn.close()


if __name__ == "__main__":
    main()
