"""Inspect Document.ТД_Поручения fields and fetch open assignments."""
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
fio = env["ERP_LOGIN"]
safe_fio = fio.replace('"', '""')
md = app.Metadata

doc = md.Documents.ТД_Поручения
print("Document:", doc.Name, "|", getattr(doc, "Synonym", ""))
print("\nAttributes:")
for i in range(doc.Attributes.Count()):
    attr = doc.Attributes.Get(i)
    print(f"  {attr.Name} — {getattr(attr, 'Synonym', '')}")

print("\nTabular sections:")
for i in range(doc.TabularSections.Count()):
    ts = doc.TabularSections.Get(i)
    print(f"  {ts.Name} — {getattr(ts, 'Synonym', '')}")
    for j in range(min(12, ts.Attributes.Count())):
        a = ts.Attributes.Get(j)
        print(f"    .{a.Name}")

# Try broad select
queries = [
    ("all_recent", """ВЫБРАТЬ ПЕРВЫЕ 10
        Д.Ссылка, Д.Номер, Д.Дата, Д.Проведен, Д.ПометкаУдаления
        ИЗ Документ.ТД_Поручения КАК Д
        ГДЕ НЕ Д.ПометкаУдаления
        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ"""),
    ("register_protocol_tasks", f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Р.Поручение.Номер, Р.Поручение.Дата, Р.Задача, Р.Исполнитель.Наименование,
        Р.Срок, Р.Выполнена
        ИЗ РегистрСведений.ТД_ЗадачиПротоколов КАК Р
        ГДЕ НЕ Р.Выполнена
            И Р.Исполнитель.Наименование = "{safe_fio}"
        УПОРЯДОЧИТЬ ПО Р.Срок УБЫВ"""),
    ("register_dept_tasks", f"""ВЫБРАТЬ ПЕРВЫЕ 20 *
        ИЗ РегистрСведений.ТД_ЗадачиОтдела КАК Р
        ГДЕ Р.Исполнитель.Наименование = "{safe_fio}" """),
]

for name, q in queries:
    print(f"\n--- {name} ---")
    try:
        table = app.NewObject("Query", q).Execute().Unload()
        print("rows:", table.Count())
        if table.Count() and hasattr(table, "Columns"):
            cols = [table.Columns.Get(i).Name for i in range(table.Columns.Count())]
            print("cols:", cols[:15])
        for i in range(min(8, table.Count())):
            row = table.Get(i)
            parts = []
            limit = table.Columns.Count() if hasattr(table, "Columns") else 8
            for ci in range(min(10, limit)):
                cn = table.Columns.Get(ci).Name if hasattr(table, "Columns") else ""
                v = getattr(row, cn, "") if cn else row
                if v not in (None, ""):
                    parts.append(f"{cn}={str(v)[:50]}")
            print(" ", " | ".join(parts))
    except Exception as exc:
        print("FAIL:", str(exc)[:300])
