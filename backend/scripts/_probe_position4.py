from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"
FOCUS = (
    "_InfoRg129887",
    "_InfoRg164801",
    "_InfoRg165101",
    "_InfoRg72945",
    "_InfoRg48583",
    "_InfoRg45482",
    "_InfoRg59343",
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
                if c.DATA_TYPE == "binary" and (c.CHARACTER_MAXIMUM_LENGTH in (16, None) or c.CHARACTER_MAXIMUM_LENGTH == 16)
            ]
            # include _RRRef style
            bin_cols = [
                c.COLUMN_NAME
                for c in cols
                if c.DATA_TYPE == "binary"
            ]
            where = " OR ".join(f"[{c}] = ?" for c in bin_cols if c.endswith("RRef") or c.endswith("_RRRef") or c.endswith("RRef"))
            # simpler: any equality on bin cols ending with Ref
            ref_cols = [c for c in bin_cols if c.endswith("RRef") or c.endswith("_RRRef")]
            if not ref_cols:
                continue
            where = " OR ".join(f"[{c}] = ?" for c in ref_cols)
            params = [emp_id] * len(ref_cols)
            cur.execute(
                f"SELECT TOP 3 * FROM dbo.[{table}] WITH (NOLOCK) WHERE {where}",
                params,
            )
            rows = cur.fetchall()
            colnames = [d[0] for d in cur.description]
            print("\n====", table, "rows", len(rows))
            if not rows:
                continue
            values = []
            for row in rows[:1]:
                for name, value in zip(colnames, row, strict=False):
                    if value is None:
                        continue
                    if name in ref_cols and value != emp_id:
                        values.append((name, value))
            # Resolve unique values
            seen = set()
            for name, value in values:
                key = bytes(value)
                if key in seen:
                    continue
                seen.add(key)
                found = None
                for pref in refs:
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
                        found = (pref, (hit.D or "").strip())
                        break
                print(f"  {name} -> {found}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
