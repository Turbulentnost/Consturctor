from __future__ import annotations

from app.clients import erp_sql

fio = "Ильченко Екатерина Александровна"
u = erp_sql.find_user_by_fio_relaxed(fio)
print("user id", u.id)
print("name", repr(u.name))
print("descr", repr(u.descr))
print("fio", u.fio)

conn = erp_sql._connect()
try:
    cur = conn.cursor()
    cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
    cur.execute(
        """
        SELECT TOP 5
            CAST(_Code AS nvarchar(64)) AS Code,
            CAST(_Description AS nvarchar(256)) AS Descr
        FROM dbo._Reference366 WITH (NOLOCK)
        WHERE _Description LIKE N'%Ильченко%' AND _Description LIKE N'%Екатерина%'
        """
    )
    for row in cur.fetchall():
        print("ref366", row.Code, row.Descr)
    # scan columns on ref366 for email-like values - sample one row
    cur.execute(
        """
        SELECT TOP 1 *
        FROM dbo._Reference366 WITH (NOLOCK)
        WHERE _Description LIKE N'%Ильченко%' AND _Description LIKE N'%Екатерина%'
        """
    )
    row = cur.fetchone()
    if row:
        cols = [d[0] for d in cur.description]
        for c, v in zip(cols, row, strict=False):
            if v is None:
                continue
            if isinstance(v, (bytes, bytearray)):
                continue
            s = str(v).strip()
            if not s:
                continue
            if "@" in s or (c.lower().find("mail") >= 0) or (c.lower().find("email") >= 0):
                print("col", c, s[:120])
            if c in ("_Code", "Code") or "login" in c.lower():
                print("col", c, s[:120])
finally:
    conn.close()
