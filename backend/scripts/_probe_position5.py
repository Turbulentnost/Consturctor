from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"
POS_CATS = ("_Reference444", "_Reference164", "_Reference73233", "_Reference185893")
INFO_REGS = (
    "_InfoRg129631",
    "_InfoRg129887",
    "_InfoRg164801",
    "_InfoRg165101",
    "_InfoRg43471X1",
    "_InfoRg43726",
    "_InfoRg45482",
    "_InfoRg45569",
    "_InfoRg47331",
    "_InfoRg48583",
    "_InfoRg49108",
    "_InfoRg50700",
    "_InfoRg59343",
    "_InfoRg72849",
    "_InfoRg72891",
    "_InfoRg72945",
)


def main() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")
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

        for table in INFO_REGS:
            cur.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
                  AND DATA_TYPE='binary'
                ORDER BY ORDINAL_POSITION
                """,
                (table,),
            )
            bin_cols = [r.COLUMN_NAME for r in cur.fetchall()]
            emp_cols = [c for c in bin_cols if c.endswith("RRef") or c.endswith("_RRRef")]
            if not emp_cols:
                continue
            emp_where = " OR ".join(f"t.[{c}] = ?" for c in emp_cols)
            emp_params = [emp_id] * len(emp_cols)

            for pos_cat in POS_CATS:
                for col in emp_cols:
                    sql = f"""
                        SELECT TOP 3 CAST(p._Description AS nvarchar(256)) AS Pos
                        FROM dbo.[{table}] t WITH (NOLOCK)
                        INNER JOIN dbo.[{pos_cat}] p WITH (NOLOCK)
                            ON t.[{col}] = p._IDRRef
                        WHERE ({emp_where})
                          AND LTRIM(RTRIM(p._Description)) <> N''
                    """
                    try:
                        cur.execute(sql, emp_params)
                        rows = [(r.Pos or "").strip() for r in cur.fetchall()]
                    except Exception:
                        continue
                    if rows:
                        print(f"HIT {table}.{col} x {pos_cat}: {rows}")

        # Also try document tables for кадровые назначения if info regs fail
        cur.execute(
            """
            SELECT TOP 200 TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE'
              AND (
                    TABLE_NAME LIKE '\\_Document%' ESCAPE '\\'
                 OR TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
              )
              AND TABLE_NAME NOT LIKE '%ChngR%'
            ORDER BY TABLE_NAME
            """
        )
        # Broader scan: any InfoRg joining employee + position catalog
        print("\nBROAD_SCAN_START")
        cur.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE'
              AND TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
              AND TABLE_NAME NOT LIKE '%ChngR%'
              AND TABLE_NAME NOT LIKE '%VT%'
            """
        )
        all_info = [r.TABLE_NAME for r in cur.fetchall()]
        print("ALL_INFO", len(all_info))
        hits = 0
        for table in all_info:
            cur.execute(
                """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
                  AND DATA_TYPE='binary'
                """,
                (table,),
            )
            cols = [r.COLUMN_NAME for r in cur.fetchall()]
            if len(cols) < 2:
                continue
            # quick existence check for employee
            where = " OR ".join(f"[{c}] = ?" for c in cols[:20])
            params = [emp_id] * min(len(cols), 20)
            try:
                cur.execute(
                    f"SELECT TOP 1 1 FROM dbo.[{table}] WITH (NOLOCK) WHERE {where}",
                    params,
                )
                if not cur.fetchone():
                    continue
            except Exception:
                continue
            for pos_cat in ("_Reference444", "_Reference164"):
                for col in cols[:20]:
                    try:
                        cur.execute(
                            f"""
                            SELECT TOP 1 CAST(p._Description AS nvarchar(256)) AS Pos
                            FROM dbo.[{table}] t WITH (NOLOCK)
                            INNER JOIN dbo.[{pos_cat}] p WITH (NOLOCK)
                                ON t.[{col}] = p._IDRRef
                            WHERE ({where})
                              AND LTRIM(RTRIM(p._Description)) <> N''
                            """,
                            params,
                        )
                        row = cur.fetchone()
                    except Exception:
                        continue
                    if row and (row.Pos or "").strip():
                        print(f"BROAD_HIT {table}.{col} x {pos_cat}: {(row.Pos or '').strip()}")
                        hits += 1
                        break
                if hits >= 20:
                    break
            if hits >= 20:
                break
        print("BROAD_DONE hits", hits)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
