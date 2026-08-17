"""Live COM: connect to ERP and list current user's open tasks."""
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

FIO = env["ERP_LOGIN"]
conn = f'Srvr="192.168.2.229";Ref="erp_pm";Usr="{FIO}";Pwd="{env["ERP_PASSWORD"]}";'

import win32com.client

connector = win32com.client.Dispatch("V83.COMConnector")
app = connector.Connect(conn)
user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
print("=== ERP COM live ===")
print("Пользователь:", user.ПолноеИмя)
print("Строка:", conn.replace(env["ERP_PASSWORD"], "***"))

queries = {
    "Мои открытые": f"""ВЫБРАТЬ ПЕРВЫЕ 30
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения, Т.Исполнитель.Наименование
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = "{FIO}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "Все открытые (топ)": """ВЫБРАТЬ ПЕРВЫЕ 15
        Т.Номер, Т.Наименование, Т.Дата, Т.Исполнитель.Наименование
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
}

for title, q in queries.items():
    print(f"\n--- {title} ---")
    table = app.NewObject("Query", q).Execute().Unload()
    print(f"найдено: {table.Count()}")
    for i in range(table.Count()):
        row = table.Get(i)
        num = str(getattr(row, "Номер", "") or "")
        name = str(getattr(row, "Наименование", "") or "")
        dt = str(getattr(row, "Дата", "") or "")[:16]
        due = str(getattr(row, "СрокИсполнения", "") or "")[:10]
        ex = str(getattr(row, "Исполнитель", "") or "")[:30]
        line = f"  {num:16} | {dt} | {name[:65]}"
        if ex and title.startswith("Все"):
            line += f" | {ex}"
        if due and due not in ("", "0001-01-01"):
            line += f" | срок {due}"
        print(line)
