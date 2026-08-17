"""Filter BusinessProcess_Задание by current user — likely «Задачи мне» on start page."""
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

# discover BP fields
md = app.Metadata
bp = md.BusinessProcesses.Задание
print("BP Задание attributes sample:")
for coll_name in ("Attributes", "TabularSections"):
    coll = getattr(bp, coll_name, None)
    if coll and coll.Count():
        names = [coll.Get(i).Name for i in range(min(15, coll.Count()))]
        print(f"  {coll_name}:", names)

queries = {
    "bp_исполнитель_имя": f"""ВЫБРАТЬ ПЕРВЫЕ 30
        Б.Номер, Б.Наименование, Б.Дата, Б.Стартован, Б.Завершен
        ИЗ БизнесПроцесс.Задание КАК Б
        ГДЕ Б.Стартован И НЕ Б.Завершен
            И Б.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Б.Дата УБЫВ""",
    "bp_автор_не_я": f"""ВЫБРАТЬ ПЕРВЫЕ 30
        Б.Номер, Б.Наименование, Б.Дата
        ИЗ БизнесПроцесс.Задание КАК Б
        ГДЕ Б.Стартован И НЕ Б.Завершен
            И Б.Исполнитель.Наименование = "{fio.replace('"', '""')}"
            И Б.Автор.Наименование <> "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Б.Дата УБЫВ""",
    "task_bp_link": f"""ВЫБРАТЬ ПЕРВЫЕ 30
        Т.Номер, Т.Наименование, Т.Дата, Т.БизнесПроцесс
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
}

for name, q in queries.items():
    print(f"\n=== {name} ===")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print("rows:", t.Count())
        for i in range(min(15, t.Count())):
            row = t.Get(i)
            print(f"  {getattr(row, 'Номер', '')} | {str(getattr(row, 'Наименование', ''))[:65]}")
    except Exception as exc:
        print("FAIL:", str(exc)[:220])
