from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"
FOCUS = (
    "_InfoRg48583",
    "_InfoRg59343",
    "_InfoRg129631",
    "_InfoRg45482",
    "_InfoRg47331",
    "_InfoRg129887",
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
            text_cols = [
                c.COLUMN_NAME
                for c in cols
                if c.DATA_TYPE in {"nvarchar", "varchar"}
            ]
            where = " OR ".join(f"[{c}] = ?" for c in ref_cols)
            params = [emp] * len(ref_cols)
            cur.execute(
                f"SELECT TOP 1 * FROM dbo.[{table}] WITH (NOLOCK) WHERE {where}",
                params,
            )
            row = cur.fetchone()
            colnames = [d[0] for d in cur.description]
            print("\n====", table, "found", bool(row))
            if not row:
                continue
            for name, value in zip(colnames, row, strict=False):
                if name in text_cols and value is not None and str(value).strip():
                    print(f" TEXT {name}: {str(value).strip()[:200]}")
            for name, value in zip(colnames, row, strict=False):
                if name not in ref_cols or value is None or value == emp:
                    continue
                found = None
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
    finally:
        conn.close()


if __name__ == "__main__":
    main()
