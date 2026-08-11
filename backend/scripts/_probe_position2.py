from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"


def main() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

        cur.execute(
            """
            SELECT
                CAST(u._Description AS nvarchar(256)) AS Emp,
                CAST(u._Fld10998 AS nvarchar(256)) AS F10998,
                CAST(u._Fld166083 AS nvarchar(256)) AS F166083,
                CAST(u._Fld166085 AS nvarchar(256)) AS F166085
            FROM dbo._Reference366 u WITH (NOLOCK)
            WHERE LTRIM(RTRIM(u._Description)) = ?
            """,
            (FIO,),
        )
        row = cur.fetchone()
        print("TEXT_FIELDS", row)

        # Find tables with Description containing typical position words and linked somehow
        cur.execute(
            """
            SELECT TOP 50 TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
              AND (
                    TABLE_NAME LIKE '[_]InfoRg%'
                 OR TABLE_NAME LIKE '[_]Reference%'
              )
              AND TABLE_NAME NOT LIKE '%ChngR%'
              AND TABLE_NAME NOT LIKE '%VT%'
            ORDER BY TABLE_NAME
            """
        )
        # Instead: find tables that have both a column referencing employee-like and Description
        cur.execute(
            """
            SELECT c.TABLE_NAME, COUNT(*) AS Cnt
            FROM INFORMATION_SCHEMA.COLUMNS c
            WHERE c.TABLE_SCHEMA = 'dbo'
              AND (
                    c.TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
                 OR c.TABLE_NAME LIKE '\\_Reference%' ESCAPE '\\'
              )
              AND c.COLUMN_NAME = '_Description'
            GROUP BY c.TABLE_NAME
            """
        )
        desc_tables = [r.TABLE_NAME for r in cur.fetchall()]
        print("DESC_TABLES", len(desc_tables))

        # Sample descriptions that look like job titles from small reference tables
        candidates = []
        for table in desc_tables:
            try:
                cur.execute(
                    f"""
                    SELECT TOP 5 CAST(_Description AS nvarchar(256)) AS D
                    FROM dbo.[{table}] WITH (NOLOCK)
                    WHERE LTRIM(RTRIM(_Description)) <> N''
                    """
                )
                samples = [(r.D or "").strip() for r in cur.fetchall()]
            except Exception:
                continue
            if not samples:
                continue
            joined = " | ".join(samples).lower()
            score = sum(
                1
                for marker in (
                    "менеджер",
                    "инженер",
                    "специалист",
                    "руководитель",
                    "директор",
                    "программист",
                    "начальник",
                    "эксперт",
                    "ассистент",
                    "аналитик",
                    "должность",
                )
                if marker in joined
            )
            if score >= 2:
                candidates.append((score, table, samples[:5]))
        candidates.sort(reverse=True)
        print("POSITION_CATALOGS")
        for item in candidates[:30]:
            print(item)

        # Find InfoRg tables that contain employee FK (_Reference366) for this user
        cur.execute(
            """
            SELECT TOP 1 u._IDRRef
            FROM dbo._Reference366 u WITH (NOLOCK)
            WHERE LTRIM(RTRIM(u._Description)) = ?
            """,
            (FIO,),
        )
        emp = cur.fetchone()
        if not emp:
            print("NO_EMP")
            return
        emp_id = emp[0]

        cur.execute(
            """
            SELECT TABLE_NAME, COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = 'dbo'
              AND TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
              AND DATA_TYPE = 'binary'
              AND CHARACTER_MAXIMUM_LENGTH = 16
            ORDER BY TABLE_NAME, ORDINAL_POSITION
            """
        )
        info_cols = cur.fetchall()
        print("INFO_BIN_COLS", len(info_cols))

        # Probe a limited set: for each InfoRg table, check if any binary16 column equals employee id
        by_table: dict[str, list[str]] = {}
        for r in info_cols:
            by_table.setdefault(r.TABLE_NAME, []).append(r.COLUMN_NAME)

        linked = []
        for table, cols in by_table.items():
            # Skip huge probing of all columns separately: OR them
            wheres = " OR ".join(f"[{c}] = ?" for c in cols[:12])
            params = [emp_id] * min(len(cols), 12)
            try:
                cur.execute(
                    f"""
                    SELECT TOP 1 1 AS X
                    FROM dbo.[{table}] WITH (NOLOCK)
                    WHERE {wheres}
                    """,
                    params,
                )
                if cur.fetchone():
                    linked.append(table)
            except Exception:
                continue
        print("LINKED_INFOREGS", len(linked))
        for table in linked[:80]:
            print(table)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
