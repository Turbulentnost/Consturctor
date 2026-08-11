from __future__ import annotations

from app.clients.erp_sql import _connect


def main() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME = '_Reference366'
            ORDER BY ORDINAL_POSITION
            """
        )
        cols = cur.fetchall()
        print("EMPLOYEE_COLS", len(cols))
        rrefs = []
        for c in cols:
            name = c.COLUMN_NAME
            print(name, c.DATA_TYPE)
            if name.endswith("RRef") and name.startswith("_Fld"):
                rrefs.append(name)

        # Find references that look like position catalogs via sample joins
        # Prefer catalogs whose description contains typical position words.
        sample_fio = "Мангасарян Давид Каренович"
        cur.execute(
            """
            SELECT TOP 1 u._IDRRef
            FROM dbo._Reference366 u WITH (NOLOCK)
            WHERE LTRIM(RTRIM(u._Description)) = ?
            """,
            (sample_fio,),
        )
        emp = cur.fetchone()
        print("EMP_FOUND", bool(emp))

        # List reference tables that might be "Должности"
        cur.execute(
            """
            SELECT t.TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES t
            WHERE t.TABLE_TYPE = 'BASE TABLE'
              AND t.TABLE_NAME LIKE '\\_Reference%' ESCAPE '\\'
              AND t.TABLE_NAME NOT LIKE '%ChngR%'
              AND t.TABLE_NAME NOT LIKE '%VT%'
            ORDER BY t.TABLE_NAME
            """
        )
        refs = [r.TABLE_NAME for r in cur.fetchall()]
        print("REF_COUNT", len(refs))

        # Probe employee RRefs against reference catalogs to find position-like texts
        if emp:
            hits = []
            for fld in rrefs:
                for ref in refs:
                    try:
                        cur.execute(
                            f"""
                            SELECT TOP 1 CAST(r._Description AS nvarchar(256)) AS Descr
                            FROM dbo._Reference366 u WITH (NOLOCK)
                            INNER JOIN dbo.[{ref}] r WITH (NOLOCK)
                                ON u.[{fld}] = r._IDRRef
                            WHERE LTRIM(RTRIM(u._Description)) = ?
                              AND LTRIM(RTRIM(r._Description)) <> N''
                            """,
                            (sample_fio,),
                        )
                        row = cur.fetchone()
                    except Exception:
                        continue
                    if not row:
                        continue
                    descr = (row.Descr or "").strip()
                    low = descr.lower()
                    score = 0
                    for marker in (
                        "менеджер",
                        "инженер",
                        "специалист",
                        "руководитель",
                        "директор",
                        "аналитик",
                        "программист",
                        "начальник",
                        "эксперт",
                        "ассистент",
                        "должность",
                    ):
                        if marker in low:
                            score += 1
                    if score or len(descr) < 80:
                        hits.append((score, fld, ref, descr))
            hits.sort(reverse=True)
            print("TOP_HITS")
            for item in hits[:40]:
                print(item)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
