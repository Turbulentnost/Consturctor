"""Discover ERP modules/registers for start-page tasks."""
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

conn = f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
import win32com.client

app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)

candidates = [
    "БизнесПроцессыИЗадачи",
    "БизнесПроцессыИЗадачиСервер",
    "БизнесПроцессыИЗадачиКлиент",
    "БизнесПроцессыИЗадачиВызовСервера",
    "РаботаСЗадачами",
    "УправлениеЗадачами",
    "ТекущиеДела",
    "ТекущиеДелаСервер",
    "НачальнаяСтраница",
    "НачальнаяСтраницаСервер",
    "ИнтеграцияС1СДокументооборот",
    "ИнтеграцияС1СДокументооборотВызовСервера",
    "ИнтеграцияС1СДокументооборотКлиент",
    "ОповещенияПользователей",
    "ОповещенияПользователейСервер",
]

for name in candidates:
    try:
        obj = getattr(app, name)
        print("MODULE OK:", name, type(obj))
    except Exception:
        pass

# registers / queries with 'дел' or notification
register_queries = {
    "reg_tasks": """ВЫБРАТЬ ПЕРВЫЕ 5 * ИЗ РегистрСведений.ИсполнителиЗадач""",
    "reg_current": """ВЫБРАТЬ ПЕРВЫЕ 5 * ИЗ РегистрСведений.ТекущиеДела""",
    "reg_notif": """ВЫБРАТЬ ПЕРВЫЕ 5 * ИЗ РегистрСведений.ОповещенияПользователей""",
    "doc_incoming": """ВЫБРАТЬ ПЕРВЫЕ 10
        Д.Номер, Д.Дата, Д.Комментарий
        ИЗ Документ.ТД_ВходящаяКорреспонденция КАК Д
        ГДЕ НЕ Д.ПометкаУдаления
        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ""",
}

for name, q in register_queries.items():
    print(f"\n--- {name} ---")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print("rows:", t.Count())
        if t.Count():
            row = t.Get(0)
            cols = [t.Columns.Get(i).Name for i in range(t.Columns.Count())]
            print("cols:", cols[:12])
    except Exception as exc:
        print("FAIL", str(exc)[:160])

# thick client attempt
print("\n=== Thick client V83.Application ===")
for progid in ("V83.Application", "V83.Application.1"):
    try:
        thick = win32com.client.Dispatch(progid)
        thick.Visible = True
        thick.Connect(conn)
        print("thick Connect OK", progid)
        user = thick.ПользователиИнформационнойБазы.ТекущийПользователь().ПолноеИмя
        print("user:", user)
        q = """ВЫБРАТЬ ПЕРВЫЕ 10 Т.Номер, Т.Наименование ИЗ Задача.ЗадачаИсполнителя КАК Т
            ГДЕ НЕ Т.Выполнена И Т.Исполнитель.Наименование = &Имя УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
        query = thick.NewObject("Query", q)
        query.SetParameter("Имя", env["ERP_LOGIN"])
        t = query.Execute().Unload()
        print("tasks:", t.Count())
        for i in range(t.Count()):
            row = t.Get(i)
            print(" ", getattr(row, "Номер", ""), str(getattr(row, "Наименование", ""))[:60])
        break
    except Exception as exc:
        print("FAIL", progid, exc)
