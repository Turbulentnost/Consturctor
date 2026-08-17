"""Find tasks/subjects with attached files in last week."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

import win32com.client

conn = (
    f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";'
    f'Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
)
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)

today = date.today()
week_start = today - timedelta(days=today.weekday() + 7)
week_end = week_start + timedelta(days=7)

queries = {
    "crm_interes_files": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Ф.Наименование, Ф.Расширение, Ф.Размер, Ф.ВладелецФайла.Номер КАК OwnerNumber,
        Ф.ДатаСоздания
        ИЗ Справочник.CRM_ИнтересПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ДатаСоздания >= ДАТАВРЕМЯ({week_start.year}, {week_start.month}, {week_start.day})
            И Ф.ДатаСоздания < ДАТАВРЕМЯ({week_end.year}, {week_end.month}, {week_end.day})
        УПОРЯДОЧИТЬ ПО Ф.ДатаСоздания УБЫВ""",
    "bp_files": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Ф.Наименование, Ф.Расширение, Ф.Размер, Ф.ВладелецФайла.Номер КАК OwnerNumber,
        Ф.ДатаСоздания
        ИЗ Справочник.CRM_БизнесПроцессПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ДатаСоздания >= ДАТАВРЕМЯ({week_start.year}, {week_start.month}, {week_start.day})
            И Ф.ДатаСоздания < ДАТАВРЕМЯ({week_end.year}, {week_end.month}, {week_end.day})
        УПОРЯДОЧИТЬ ПО Ф.ДатаСоздания УБЫВ""",
    "my_tasks_week": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата, Т.Предмет.Номер КАК SubjectNumber,
        Т.Предмет.Метаданные().Имя КАК SubjectType
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ Т.Дата >= ДАТАВРЕМЯ({week_start.year}, {week_start.month}, {week_start.day})
            И Т.Дата < ДАТАВРЕМЯ({week_end.year}, {week_end.month}, {week_end.day})
            И Т.Исполнитель.Наименование = "{env['ERP_LOGIN'].replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
}

for name, q in queries.items():
    print(f"\n=== {name} ===")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print("rows:", t.Count())
        for i in range(min(10, t.Count())):
            r = t.Get(i)
            parts = []
            for attr in dir(r):
                if attr.startswith("_"):
                    continue
            # print common fields
            for field in (
                "Номер", "Number", "Наименование", "Name", "Расширение", "Ext",
                "Размер", "Size", "OwnerNumber", "SubjectNumber", "SubjectType", "Дата", "Date",
            ):
                val = getattr(r, field, None)
                if val not in (None, "", False):
                    parts.append(f"{field}={str(val)[:60]}")
            print(" ", " | ".join(parts[:8]))
    except Exception as exc:
        print("FAIL:", str(exc)[:250])
