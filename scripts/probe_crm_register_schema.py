"""Inspect CRM_ЗадачиПользователей register schema and sample rows."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip().strip('"').strip("'")

import win32com.client

conn = (
    f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";'
    f'Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
)
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
md = app.Metadata
reg = md.InformationRegisters.CRM_ЗадачиПользователей
print("Register:", reg.Name)
for label, coll in (("Dimensions", reg.Dimensions), ("Resources", reg.Resources), ("Attributes", reg.Attributes)):
    print(f"\n=== {label} ===")
    for i in range(coll.Count()):
        item = coll.Get(i)
        print(f"  {item.Name}")

fio = env["ERP_LOGIN"]
queries = {
    "star_top5": "ВЫБРАТЬ ПЕРВЫЕ 5 * ИЗ РегистрСведений.CRM_ЗадачиПользователей",
    "mine_top10": f"""ВЫБРАТЬ ПЕРВЫЕ 10 *
        ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
        ГДЕ Р.Пользователь.Наименование = "{fio.replace('"', '""')}" """,
}
for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        table = app.NewObject("Query", q).Execute().Unload()
        print("rows:", table.Count())
        if table.Count():
            cols = [table.Columns.Get(i).Name for i in range(table.Columns.Count())]
            print("columns:", cols)
            for ri in range(min(3, table.Count())):
                row = table.Get(ri)
                parts = []
                for c in cols[:8]:
                    parts.append(f"{c}={str(getattr(row, c, ''))[:40]}")
                print(" ", " | ".join(parts))
    except Exception as exc:
        print("FAIL", str(exc)[:240])
