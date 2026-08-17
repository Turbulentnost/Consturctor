"""Test 1C COM query result iteration methods."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

conn = f'Srvr="192.168.2.229";Ref="erp_pm";Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
import win32com.client

app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
q = """ВЫБРАТЬ ПЕРВЫЕ 5
    Т.Наименование, Т.Дата, Т.Номер, Т.Исполнитель.Наименование
    ИЗ Задача.ЗадачаИсполнителя КАК Т
    ГДЕ НЕ Т.Выполнена
    УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
query = app.NewObject("Query", q)
result = query.Execute()

for label, method in (
    ("Select", lambda r: r.Select()),
    ("Choose+Select", lambda r: r.Choose().Select()),
):
    try:
        sel = method(result)
        n = 0
        while sel.Next() and n < 5:
            n += 1
            print(label, n, sel.Наименование, sel.Дата)
        print(label, "count", n)
    except Exception as exc:
        print(label, "FAIL", exc)

try:
    table = result.Unload()
    print("Unload Count()", table.Count(), "Columns", table.Columns.Count())
    for i in range(min(5, table.Count())):
        row = table.Get(i)
        print(" row", i, row.Наименование, row.Дата, row.Номер)
except Exception as exc:
    print("Unload FAIL", exc)
