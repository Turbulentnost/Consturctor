from __future__ import annotations

from app.clients import erp_sql

conn = erp_sql._connect()
try:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME = '_Reference366'
        ORDER BY ORDINAL_POSITION
        """
    )
    cols = cur.fetchall()
    print("column count", len(cols))
    for c in cols:
        if c.DATA_TYPE in ("nvarchar", "varchar", "nchar", "char"):
            print(c.COLUMN_NAME, c.DATA_TYPE)

    cur.execute(
        """
        SELECT TOP 1 *
        FROM dbo._Reference366 WITH (NOLOCK)
        WHERE _Description LIKE N'%Ильченко%' AND _Description LIKE N'%Екатерина%'
        """
    )
    row = cur.fetchone()
    if not row:
        print("no row")
    else:
        names = [d[0] for d in cur.description]
        for name, val in zip(names, row, strict=False):
            if val is None or isinstance(val, (bytes, bytearray)):
                continue
            s = str(val).strip()
            if s and len(s) < 300:
                print("FIELD", name, repr(s))
finally:
    conn.close()
