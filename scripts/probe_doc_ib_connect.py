"""Try COM connect to document-flow IB names."""
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

refs = ["doc", "dterp", "doc_pm", "erp_doc", "DocumentManagement", "erp_pm"]
server = env["ONEC_COM_SERVER"]
user = env["ERP_LOGIN"]
password = env["ERP_PASSWORD"]

for ref in refs:
    conn = f'Srvr="{server}";Ref="{ref}";Usr="{user}";Pwd="{password}";'
    try:
        app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
        current = app.ПользователиИнформационнойБазы.ТекущийПользователь().ПолноеИмя
        q = """ВЫБРАТЬ ПЕРВЫЕ 5
            Т.Номер, Т.Наименование, Т.СрокИсполнения
            ИЗ Задача.ЗадачаИсполнителя КАК Т
            ГДЕ НЕ Т.Выполнена
            УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
        table = app.NewObject("Query", q).Execute().Unload()
        print(f"{ref}: OK user={current} open={table.Count()}")
        for i in range(min(3, table.Count())):
            row = table.Get(i)
            print(
                " ",
                getattr(row, "Number", ""),
                str(getattr(row, "Description", ""))[:70],
            )
    except Exception as exc:
        print(f"{ref}: FAIL {str(exc)[:150]}")
