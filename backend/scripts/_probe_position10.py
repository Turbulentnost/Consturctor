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
            SELECT TOP 1 u._IDRRef
            FROM dbo._Reference366 u WITH (NOLOCK)
            WHERE LTRIM(RTRIM(u._Description)) = ?
            """,
            (FIO,),
        )
        emp = cur.fetchone()[0]

        # Type marker for position catalog from a known join pattern using RTRef
        cur.execute(
            """
            SELECT TOP 1 CONVERT(varchar(8), _IDRRef, 2) AS HexId,
                   CAST(_Description AS nvarchar(256)) AS D
            FROM dbo._Reference444 WITH (NOLOCK)
            WHERE LTRIM(RTRIM(_Description)) <> N''
            """
        )
        sample = cur.fetchone()
        print("POS_SAMPLE", sample.D if sample else None, sample.HexId if sample else None)

        # Find InfoRg tables that have BOTH employee id and a value from _Reference444
        # Use EXISTS with CROSS APPLY style limited set of candidate tables that contain emp id
        cur.execute(
            """
            SELECT TABLE_NAME, COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA='dbo'
              AND TABLE_NAME LIKE '\\_InfoRg%' ESCAPE '\\'
              AND TABLE_NAME NOT LIKE '%ChngR%'
              AND TABLE_NAME NOT LIKE '%VT%'
              AND DATA_TYPE='binary'
              AND (
                    COLUMN_NAME LIKE '%RRef'
                 OR COLUMN_NAME LIKE '%\\_RRRef' ESCAPE '\\'
              )
            ORDER BY TABLE_NAME, ORDINAL_POSITION
            """
        )
        by_table: dict[str, list[str]] = {}
        for r in cur.fetchall():
            by_table.setdefault(r.TABLE_NAME, []).append(r.COLUMN_NAME)

        # First pass: tables where employee appears
        linked = []
        for table, cols in by_table.items():
            where = " OR ".join(f"[{c}] = ?" for c in cols[:12])
            params = [emp] * min(len(cols), 12)
            try:
                cur.execute(
                    f"SELECT TOP 1 1 FROM dbo.[{table}] WITH (NOLOCK) WHERE {where}",
                    params,
                )
                if cur.fetchone():
                    linked.append((table, cols))
            except Exception:
                continue
        print("LINKED", len(linked))

        for table, cols in linked:
            emp_where = " OR ".join(f"t.[{c}] = ?" for c in cols[:12])
            emp_params = [emp] * min(len(cols), 12)
            for pos_cat in ("_Reference444", "_Reference164", "_Reference185893", "_Reference73233"):
                for pos_col in cols[:12]:
                    try:
                        cur.execute(
                            f"""
                            SELECT TOP 3 CAST(p._Description AS nvarchar(256)) AS Pos
                            FROM dbo.[{table}] t WITH (NOLOCK)
                            INNER JOIN dbo.[{pos_cat}] p WITH (NOLOCK)
                              ON t.[{pos_col}] = p._IDRRef
                            WHERE ({emp_where})
                              AND LTRIM(RTRIM(p._Description)) <> N''
                            """,
                            emp_params,
                        )
                        rows = [(r.Pos or "").strip() for r in cur.fetchall()]
                    except Exception:
                        continue
                    if rows:
                        print(f"HIT {table}.{pos_col} <- {pos_cat}: {rows}")

        # Also search document tables linked to employee + position
        print("DOC_SCAN")
        cur.execute(
            """
            SELECT TABLE_NAME, COLUMN_NAME
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA='dbo'
              AND TABLE_NAME LIKE '\\_Document%' ESCAPE '\\'
              AND TABLE_NAME NOT LIKE '%ChngR%'
              AND TABLE_NAME NOT LIKE '%VT%'
              AND DATA_TYPE='binary'
              AND (
                    COLUMN_NAME LIKE '%RRef'
                 OR COLUMN_NAME LIKE '%\\_RRRef' ESCAPE '\\'
              )
            """
        )
        docs: dict[str, list[str]] = {}
        for r in cur.fetchall():
            docs.setdefault(r.TABLE_NAME, []).append(r.COLUMN_NAME)
        doc_linked = []
        for table, cols in docs.items():
            where = " OR ".join(f"[{c}] = ?" for c in cols[:12])
            params = [emp] * min(len(cols), 12)
            try:
                cur.execute(
                    f"SELECT TOP 1 1 FROM dbo.[{table}] WITH (NOLOCK) WHERE {where}",
                    params,
                )
                if cur.fetchone():
                    doc_linked.append((table, cols))
            except Exception:
                continue
        print("DOC_LINKED", len(doc_linked))
        for table, cols in doc_linked:
            emp_where = " OR ".join(f"t.[{c}] = ?" for c in cols[:12])
            emp_params = [emp] * min(len(cols), 12)
            for pos_col in cols[:12]:
                try:
                    cur.execute(
                        f"""
                        SELECT TOP 1 CAST(p._Description AS nvarchar(256)) AS Pos
                        FROM dbo.[{table}] t WITH (NOLOCK)
                        INNER JOIN dbo._Reference444 p WITH (NOLOCK)
                          ON t.[{pos_col}] = p._IDRRef
                        WHERE ({emp_where})
                          AND LTRIM(RTRIM(p._Description)) <> N''
                        """,
                        emp_params,
                    )
                    hit = cur.fetchone()
                except Exception:
                    continue
                if hit and (hit.Pos or "").strip():
                    print(f"DOC_HIT {table}.{pos_col}: {(hit.Pos or '').strip()}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
