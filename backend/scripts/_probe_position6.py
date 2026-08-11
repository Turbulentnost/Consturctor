from __future__ import annotations

from app.clients.erp_sql import _connect

FIO = "Мангасарян Давид Каренович"


def main() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED")

        print("PERSON_COLS")
        cur.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_NAME='_Reference596'
            ORDER BY ORDINAL_POSITION
            """
        )
        person_cols = cur.fetchall()
        for r in person_cols:
            print(r.COLUMN_NAME, r.DATA_TYPE, r.CHARACTER_MAXIMUM_LENGTH)

        print("\nEMP_VT_TABLES")
        cur.execute(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE='BASE TABLE'
              AND TABLE_NAME LIKE '\\_Reference366%' ESCAPE '\\'
            ORDER BY TABLE_NAME
            """
        )
        for r in cur.fetchall():
            print(r.TABLE_NAME)

        # Resolve person RRefs for this employee against all refs (limited fields)
        cur.execute(
            """
            SELECT TOP 1 *
            FROM dbo._Reference596 p WITH (NOLOCK)
            WHERE LTRIM(RTRIM(p._Description)) = ?
            """,
            (FIO,),
        )
        prow = cur.fetchone()
        print("\nPERSON_FOUND", bool(prow))
        if not prow:
            return
        pcols = [d[0] for d in cur.description]
        pref_vals = []
        for name, value in zip(pcols, prow, strict=False):
            if value is not None and name.endswith("RRef"):
                pref_vals.append((name, value))
        print("PERSON_RREF_FIELDS", [n for n, _ in pref_vals])

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

        for name, value in pref_vals:
            found = None
            for ref in refs:
                try:
                    cur.execute(
                        f"""
                        SELECT TOP 1 CAST(_Description AS nvarchar(256)) AS D
                        FROM dbo.[{ref}] WITH (NOLOCK)
                        WHERE _IDRRef = ?
                        """,
                        (value,),
                    )
                    hit = cur.fetchone()
                except Exception:
                    continue
                if hit and (hit.D or "").strip():
                    found = (ref, (hit.D or "").strip())
                    break
            print(f"{name} -> {found}")

        # Dump nvarchar fields from person
        for r in person_cols:
            if r.DATA_TYPE in {"nvarchar", "varchar"} and r.COLUMN_NAME.startswith("_Fld"):
                idx = pcols.index(r.COLUMN_NAME)
                print("PERSON_TEXT", r.COLUMN_NAME, (prow[idx] or "").strip() if prow[idx] is not None else None)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
