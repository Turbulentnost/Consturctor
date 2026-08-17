"""Probe Document Flow «Задачи мне» — match GUI screenshot."""
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
md = app.Metadata

print("=== GUI ожидает (из скрина) ===")
print("Модуль: Документооборот → Задачи мне (1)")
print("Задача: Исполнить задачу №2")
print("Срок: 14.08.2025 | Автор: Соломичева С.В.")
print("Текст: Конструктор. Разработать KPI для ИИ-агентов")
print()

print("=== Метаданные: Документооборот / ТД / интеграция ДО ===")
for coll_name in ("CommonModules", "Reports", "DataProcessors", "CommonForms", "InformationRegisters"):
    coll = getattr(md, coll_name)
    hits = [
        coll.Get(i).Name
        for i in range(coll.Count())
        if any(x in coll.Get(i).Name for x in ("Документооборот", "ТД_", "ИнтеграцияС1СД", "Задач"))
    ]
    if hits:
        print(f"\n{coll_name} ({len(hits)}):")
        for h in hits[:25]:
            print(" ", h)
        if len(hits) > 25:
            print(f"  ... +{len(hits)-25}")

print("\n=== API интеграции с ДО ===")
for obj_name in (
    "ИнтеграцияС1СДокументооборот",
    "ИнтеграцияС1СДокументооборотКлиент",
    "ИнтеграцияС1СДокументооборотВызовСервера",
    "ТД_Документооборот",
    "ТД_ДокументооборотСервер",
    "ТД_ДокументооборотКлиент",
):
    try:
        obj = getattr(app, obj_name)
        methods = [
            m for m in dir(obj)
            if not m.startswith("_") and any(x in m for x in ("Задач", "Получ", "Спис", "Мне", "Исполн"))
        ]
        if methods:
            print(f"\n{obj_name}: {methods[:20]}")
    except Exception as exc:
        print(f"{obj_name}: FAIL {exc}")

print("\n=== Запросы: найти «Исполнить задачу №2» / KPI / Соломичева ===")
queries = {
    "task_by_name": """ВЫБРАТЬ ПЕРВЫЕ 10
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения,
        Т.Исполнитель.Наименование, Т.Автор.Наименование, Т.Описание
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ Т.Наименование ПОДОБНО "%Исполнить задачу%"
            ИЛИ Т.Наименование ПОДОБНО "%задачу №2%"
            ИЛИ Т.Описание ПОДОБНО "%KPI%"
            ИЛИ Т.Описание ПОДОБНО "%ИИ-агент%"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "task_author_solom": """ВЫБРАТЬ ПЕРВЫЕ 10
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения,
        Т.Исполнитель.Наименование, Т.Автор.Наименование
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ Т.Автор.Наименование ПОДОБНО "%Соломич%"
            И НЕ Т.Выполнена
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "task_mine_open": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения,
        Т.Исполнитель.Наименование, Т.Автор.Наименование, Т.ПринятаКИсполнению
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "bp_zadanie_mine": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Б.Номер, Б.Наименование, Б.Дата, Б.СрокИсполнения,
        Б.Исполнитель.Наименование, Б.Автор.Наименование
        ИЗ БизнесПроцесс.Задание КАК Б
        ГДЕ Б.Стартован И НЕ Б.Завершен
            И Б.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Б.Дата УБЫВ""",
    "td_incoming_with_tasks": """ВЫБРАТЬ ПЕРВЫЕ 5
        Д.Номер, Д.Дата, Д.Комментарий
        ИЗ Документ.ТД_ВходящаяКорреспонденция КАК Д
        ГДЕ Д.Комментарий ПОДОБНО "%KPI%"
            ИЛИ Д.Комментарий ПОДОБНО "%ИИ-агент%"
            ИЛИ Д.Комментарий ПОДОБНО "%совещан%"
        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ""",
}

for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print("rows:", t.Count())
        for i in range(min(10, t.Count())):
            row = t.Get(i)
            parts = []
            for col in ("Номер", "Наименование", "Дата", "СрокИсполнения", "Исполнитель", "Автор", "Описание", "Комментарий"):
                v = getattr(row, col, None)
                if v not in (None, ""):
                    parts.append(f"{col}={str(v)[:55]}")
            print(" ", " | ".join(parts) if parts else row)
    except Exception as exc:
        print("FAIL:", str(exc)[:250])

# Try DO integration methods
print("\n=== Вызовы ИнтеграцияС1СДокументооборот ===")
try:
    do = app.ИнтеграцияС1СДокументооборот
    user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
    for method in dir(do):
        if not method.startswith("_") and "Задач" in method:
            try:
                fn = getattr(do, method)
                for args in ([], [user], [fio], [user, False], [user, True]):
                    try:
                        r = fn(*args)
                        print(f"  {method}{args} -> {type(r)}", str(r)[:120])
                        break
                    except Exception:
                        pass
            except Exception:
                pass
except Exception as exc:
    print("FAIL:", exc)
