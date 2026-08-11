from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"
VTS = ("_Reference366_VT11004", "_Reference366_VT11009", "_Reference366_VT166088")
POS_CATS = (
    "_Reference444",
    "_Reference164",
    "_Reference73233",
    "_Reference185893",
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

        for vt in VTS:
            print("\n====", vt)
            cur.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME=?
                ORDER BY ORDINAL_POSITION
                """,
                (vt,),
            )
            cols = cur.fetchall()
            for c in cols:
                print(" ", c.COLUMN_NAME, c.DATA_TYPE, c.CHARACTER_MAXIMUM_LENGTH)

            # Find owner key column - usually _Reference366_IDRRef
            owner_cols = [c.COLUMN_NAME for c in cols if "IDRRef" in c.COLUMN_NAME or c.COLUMN_NAME.endswith("RRef")]
            print(" owner-like", owner_cols)
            owner = None
            for cand in owner_cols:
                try:
                    cur.execute(
                        f"SELECT TOP 5 * FROM dbo.[{vt}] WITH (NOLOCK) WHERE [{cand}] = ?",
                        (emp_id,),
                    )
                    rows = cur.fetchall()
                except Exception:
                    continue
                if rows:
                    owner = cand
                    colnames = [d[0] for d in cur.description]
                    print(" rows", len(rows), "via", cand)
                    for row in rows[:5]:
                        print(" ROW")
                        for name, value in zip(colnames, row, strict=False):
                            if value is None:
                                continue
                            if isinstance(value, (bytes, bytearray)):
                                # resolve
                                found = None
                                for pref in list(POS_CATS) + refs:
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
                                        if pref in POS_CATS or any(
                                            m in found[1].lower()
                                            for m in (
                                                "менеджер",
                                                "инженер",
                                                "специалист",
                                                "директор",
                                                "начальник",
                                                "руководитель",
                                            )
                                        ):
                                            break
                                        # keep first non-empty but continue searching for better
                                print(f"  {name}: {found if found else value[:8].hex()}")
                            else:
                                text = str(value).strip()
                                if text:
                                    print(f"  {name}: {text}")
                    break
            if owner is None:
                print(" no rows for employee")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
