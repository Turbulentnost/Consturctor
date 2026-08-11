from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"
POSITION_REFS = ("_Reference444", "_Reference164", "_Reference73233", "_Reference185893")
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
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
                ORDER BY ORDINAL_POSITION
                """,
                (table,),
            )
            cols = cur.fetchall()
            bin_cols = [
                c.COLUMN_NAME
                for c in cols
                if c.DATA_TYPE == "binary" and c.CHARACTER_MAXIMUM_LENGTH == 16
            ]
            print("\nTABLE", table, "cols", len(cols), "bin16", bin_cols)

            # Find rows for employee
            where = " OR ".join(f"[{c}] = ?" for c in bin_cols)
            params = [emp_id] * len(bin_cols)
            try:
                cur.execute(
                    f"SELECT TOP 5 * FROM dbo.[{table}] WITH (NOLOCK) WHERE {where}",
                    params,
                )
                rows = cur.fetchall()
            except Exception as exc:
                print("  query_fail", exc)
                continue
            print("  rows", len(rows))
            if not rows:
                continue

            # For each binary column value in first row, try resolve against position catalogs
            colnames = [d[0] for d in cur.description]
            for row in rows[:2]:
                for name, value in zip(colnames, row, strict=False):
                    if name not in bin_cols or value is None:
                        continue
                    for pref in POSITION_REFS:
                        try:
                            cur.execute(
                                f"""
                                SELECT TOP 1 CAST(_Description AS nvarchar(256)) AS D
                                FROM dbo.[{pref}] WITH (NOLOCK)
                                WHERE _IDRRef = ?
                                """,
                                (value,),
                            )
                            hit = cur.fetchone()
                        except Exception:
                            continue
                        if hit and (hit.D or "").strip():
                            print(f"  HIT {table}.{name} -> {pref}: {(hit.D or '').strip()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
