"""Check CRM register Закрыта/Статус values for current user."""
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
q = f"""ВЫБРАТЬ
    Р.Номер, Р.Наименование, Р.Закрыта, Р.Статус, Р.Поставлено
    ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
    ГДЕ Р.Пользователь.Наименование = "{fio.replace('"', '""')}" """
table = app.NewObject("Query", q).Execute().Unload()
print("rows", table.Count())
for i in range(table.Count()):
    row = table.Get(i)
    print(
        str(getattr(row, "Номер", "")),
        "|",
        str(getattr(row, "Наименование", ""))[:50],
        "| Закрыта=",
        str(getattr(row, "Закрыта", "")),
        "| Статус=",
        str(getattr(row, "Статус", ""))[:30],
    )
