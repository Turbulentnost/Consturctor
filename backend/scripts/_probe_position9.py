from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"
FOCUS = (
    "_InfoRg164801",
    "_InfoRg165101",
    "_InfoRg43471X1",
    "_InfoRg43726",
    "_InfoRg45569",
    "_InfoRg49108",
    "_InfoRg50700",
    "_InfoRg72849",
    "_InfoRg72891",
)
POS_CATS = ("_Reference444", "_Reference164", "_Reference73233", "_Reference185893")


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
        emp = cur.fetchone()[0]

        cur.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE'
              AND TABLE_NAME LIKE '\\_Reference%' ESCAPE '\\'
              AND TABLE_NAME NOT LIKE '%ChngR%'
              AND TABLE_NAME NOT LIKE '%VT%'
            """
        )
        refs = [r.TABLE_NAME for r in cur.fetchall()]

        for table in FOCUS:
            cur.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
                ORDER BY ORDINAL_POSITION
                """,
                (table,),
            )
            cols = cur.fetchall()
            ref_cols = [
                c.COLUMN_NAME
                for c in cols
                if c.DATA_TYPE == "binary"
                and (c.COLUMN_NAME.endswith("RRef") or c.COLUMN_NAME.endswith("_RRRef"))
            ]
            text_cols = [c.COLUMN_NAME for c in cols if c.DATA_TYPE in {"nvarchar", "varchar"}]
            where = " OR ".join(f"[{c}] = ?" for c in ref_cols)
            params = [emp] * len(ref_cols)
            cur.execute(
                f"SELECT TOP 3 * FROM dbo.[{table}] WITH (NOLOCK) WHERE {where}",
                params,
            )
            rows = cur.fetchall()
            colnames = [d[0] for d in cur.description]
            print("\n====", table, "rows", len(rows))
            if not rows:
                continue
            for row in rows[:1]:
                for name, value in zip(colnames, row, strict=False):
                    if name in text_cols and value is not None and str(value).strip():
                        print(f" TEXT {name}: {str(value).strip()[:180]}")
                for name, value in zip(colnames, row, strict=False):
                    if name not in ref_cols or value is None:
                        continue
                    # Prefer position catalogs
                    found = None
                    for pref in POS_CATS:
                        try:
                            cur.execute(
                                f"""
                                SELECT TOP 1 CAST(_Description AS nvarchar(256)) AS D
                                FROM dbo.[{pref}] WITH (NOLOCK)
                                WHERE _IDRRef = ?
                                """,
                                (bytes(value),),
                            )
                            hit = cur.fetchone()
                        except Exception:
                            continue
                        if hit and (hit.D or "").strip():
                            found = (pref, (hit.D or "").strip())
                            break
                    if found is None:
                        for ref in refs:
                            try:
                                cur.execute(
                                    f"""
                                    SELECT TOP 1 CAST(_Description AS nvarchar(256)) AS D
                                    FROM dbo.[{ref}] WITH (NOLOCK)
                                    WHERE _IDRRef = ?
                                    """,
                                    (bytes(value),),
                                )
                                hit = cur.fetchone()
                            except Exception:
                                continue
                            if hit and (hit.D or "").strip():
                                found = (ref, (hit.D or "").strip())
                                break
                    print(f" REF {name}: {found}")

        # Direct: does any InfoRg row contain employee and position from _Reference444?
        print("\nDIRECT_EMP_POS_JOIN")
        cur.execute(
            """
            SELECT TABLE_NAME, COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA='dbo'
              AND TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
              AND DATA_TYPE='binary'
              AND (
                    COLUMN_NAME LIKE '%RRef'
                 OR COLUMN_NAME LIKE '%_RRRef'
              )
            """
        )
        by_table: dict[str, list[str]] = {}
        for r in cur.fetchall():
            by_table.setdefault(r.TABLE_NAME, []).append(r.COLUMN_NAME)

        checked = 0
        for table, cols in by_table.items():
            if len(cols) < 2:
                continue
            # employee in any col, position (_Reference444) in any other col
            emp_where = " OR ".join(f"t.[{c}] = ?" for c in cols[:15])
            emp_params = [emp] * min(len(cols), 15)
            for pos_col in cols[:15]:
                sql = f"""
                    SELECT TOP 1 CAST(p._Description AS nvarchar(256)) AS Pos
                    FROM dbo.[{table}] t WITH (NOLOCK)
                    INNER JOIN dbo._Reference444 p WITH (NOLOCK)
                        ON t.[{pos_col}] = p._IDRRef
                    WHERE ({emp_where})
                      AND LTRIM(RTRIM(p._Description)) <> N''
                """
                try:
                    cur.execute(sql, emp_params)
                    hit = cur.fetchone()
                except Exception:
                    continue
                checked += 1
                if hit and (hit.Pos or "").strip():
                    print(f"JOIN_HIT {table}.{pos_col}: {(hit.Pos or '').strip()}")
        print("checked_joins", checked)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
