"""Deep probe: ИнтеграцияС1СДокументооборот — «Задачи мне» from screenshot."""
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

print("=== DataProcessor ИнтеграцияС1СДокументооборот ===")
try:
    proc = app.DataProcessors.ИнтеграцияС1СДокументооборот.Create()
    print("Create OK")
    methods = sorted(
        m for m in dir(proc)
        if not m.startswith("_") and any(x in m for x in ("Задач", "Получ", "Спис", "Обнов", "Подключ", "Синхрон"))
    )
    print("methods:", methods[:30])
    for method in methods[:15]:
        try:
            fn = getattr(proc, method)
            r = fn()
            print(f"  {method}() -> {type(r)} {str(r)[:150]}")
        except Exception as exc:
            print(f"  {method}() FAIL: {str(exc)[:100]}")
except Exception as exc:
    print("FAIL:", exc)

print("\n=== CommonModule БизнесПроцессыИЗадачиСервер ===")
for mod_name in (
    "БизнесПроцессыИЗадачиСервер",
    "БизнесПроцессыИЗадачиВызовСервера",
    "ИнтеграцияС1СДокументооборотБазоваяФункциональность",
):
    try:
        mod = getattr(app, mod_name)
        methods = [m for m in dir(mod) if "Задач" in m and not m.startswith("_")]
        print(f"{mod_name}: {methods[:15]}")
        for method in methods[:8]:
            try:
                user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
                r = getattr(mod, method)(user)
                print(f"  {method}(user) -> {type(r)} count={getattr(r,'Count',lambda: '?')()}")
            except Exception as exc:
                print(f"  {method} FAIL: {str(exc)[:90]}")
    except Exception as exc:
        print(f"{mod_name}: no access {exc}")

print("\n=== Точный поиск задачи со скрина ===")
queries = {
    "exact_title": """ВЫБРАТЬ ПЕРВЫЕ 5
        Т.Ссылка, Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения,
        Т.Выполнена, Т.ПринятаКИсполнению,
        Т.Исполнитель.Наименование, Т.Автор.Наименование, Т.Описание
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ Т.Наименование = \"Исполнить задачу №2\"
            И НЕ Т.Выполнена""",
    "solom_mine_kpi": f"""ВЫБРАТЬ ПЕРВЫЕ 10
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения, Т.Описание,
        Т.Исполнитель.Наименование, Т.Автор.Наименование
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Автор.Наименование ПОДОБНО \"%Соломич%\"
            И Т.Исполнитель.Наименование = \"{fio.replace('"', '""')}\"
            И (Т.Описание ПОДОБНО \"%KPI%\" ИЛИ Т.Описание ПОДОБНО \"%ИИ%\" ИЛИ Т.Наименование ПОДОБНО \"%задачу №2%\")""",
    "deadline_14082025": f"""ВЫБРАТЬ ПЕРВЫЕ 10
        Т.Номер, Т.Наименование, Т.СрокИсполнения,
        Т.Исполнитель.Наименование, Т.Автор.Наименование, Т.Описание
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = \"{fio.replace('"', '""')}\"
            И Т.СрокИсполнения МЕЖДУ ДАТАВРЕМЯ(2025, 8, 14, 0, 0, 0) И ДАТАВРЕМЯ(2025, 8, 15, 0, 0, 0)""",
    "register_ispolniteli": f"""ВЫБРАТЬ ПЕРВЫЕ 20 *
        ИЗ РегистрСведений.ИсполнителиЗадач КАК Р
        ГДЕ Р.Исполнитель.Наименование = \"{fio.replace('"', '""')}\"""",
    "integrated_do_objects": """ВЫБРАТЬ ПЕРВЫЕ 10 *
        ИЗ РегистрСведений.ОбъектыИнтегрированныеС1СДокументооборотом""",
}

for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print("rows:", t.Count())
        if t.Count() and t.Columns.Count():
            cols = [t.Columns.Get(i).Name for i in range(min(8, t.Columns.Count()))]
            print("cols:", cols)
        for i in range(min(5, t.Count())):
            row = t.Get(i)
            parts = []
            for ci in range(min(8, t.Columns.Count())):
                cn = t.Columns.Get(ci).Name
                v = getattr(row, cn, "")
                if v not in (None, ""):
                    parts.append(f"{cn}={str(v)[:45]}")
            print(" ", " | ".join(parts))
    except Exception as exc:
        print("FAIL:", str(exc)[:220])
