"""Verify COM DB content and query tasks by executor name."""
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

app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
print("user:", app.ПользователиИнформационнойБазы.ТекущийПользователь().ПолноеИмя)

checks = [
    ("tasks_all", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК C ИЗ Задача.ЗадачаИсполнителя"),
    ("org", "ВЫБРАТЬ ПЕРВЫЕ 3 Организация.Наименование КАК N ИЗ Справочник.Организации КАК Организация"),
    ("users_cnt", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК C ИЗ Справочник.Пользователи"),
    (
        "my_tasks_by_name",
        f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Наименование КАК N, Т.Дата КАК D, Т.Номер КАК Num
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = "{FIO}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    ),
    (
        "my_tasks_like",
        f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Наименование КАК N, Т.Дата КАК D
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование ПОДОБНО "%Жалыбин%"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    ),
    (
        "recent_tasks",
        """ВЫБРАТЬ ПЕРВЫЕ 10
        Т.Наименование, Т.Дата, Т.Исполнитель.Наименование
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    ),
]

for name, q in checks:
    print(f"\n--- {name} ---")
    try:
        sel = app.NewObject("Query", q).Execute().Choose().Select()
        rows = []
        while sel.Next() and len(rows) < 15:
            if name.endswith("_cnt") or name == "tasks_all":
                rows.append(str(getattr(sel, "C", "")))
            else:
                parts = []
                for f in ("Num", "D", "N", "Наименование", "Дата", "Исполнитель"):
                    val = getattr(sel, f, None)
                    if val not in (None, ""):
                        parts.append(str(val)[:60])
                rows.append(" | ".join(parts) if parts else str(sel))
        print("rows:", len(rows), rows[:10])
    except Exception as exc:
        print("FAIL", exc)
