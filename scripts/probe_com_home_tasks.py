"""Probe 1C home-page task APIs via COM (match GUI start page)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#") or "=" in line:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

for k, v in env.items():
    os.environ[k] = v

conn = f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'

import win32com.client

print("=== Active 1C GUI ===")
for progid in (
    "V83.Application",
    "V83c.Application",
    "V83.Application.1",
    "V83c.Application.1",
    "V83COMConnector.Application",
):
    try:
        obj = win32com.client.GetActiveObject(progid)
        print("GetActiveObject OK:", progid, type(obj))
    except Exception as exc:
        print("GetActiveObject FAIL:", progid, exc)

print("\n=== COMConnector session ===")
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
print("user:", user.ПолноеИмя)

# Try standard home-page APIs
api_calls = [
    ("БизнесПроцессыИЗадачи", "ПолучитьЗадачиПользователя", [user]),
    ("БизнесПроцессыИЗадачи", "ПолучитьЗадачиПользователя", [user, False]),
    ("БизнесПроцессыИЗадачи", "ПолучитьЗадачиПользователя", [user, True]),
    ("БизнесПроцессыИЗадачи", "ЗадачиПользователя", [user]),
]

for mgr, method, args in api_calls:
    print(f"\n--- {mgr}.{method} ---")
    try:
        obj = getattr(app, mgr)
        result = getattr(obj, method)(*args)
        print("type:", type(result))
        if hasattr(result, "Count"):
            print("Count:", result.Count())
            for i in range(min(10, result.Count())):
                item = result.Get(i) if hasattr(result, "Get") else result[i]
                name = str(getattr(item, "Наименование", getattr(item, "Description", item)))[:70]
                num = str(getattr(item, "Номер", getattr(item, "Number", "")))[:20]
                print(f"  {num} | {name}")
        elif hasattr(result, "Unload"):
            t = result.Unload()
            print("Unload Count:", t.Count())
            for i in range(min(10, t.Count())):
                row = t.Get(i)
                print(f"  {getattr(row, 'Number', '')} | {str(getattr(row, 'Description', getattr(row, 'Наименование', '')))[:70]}")
        else:
            print("result:", str(result)[:200])
    except Exception as exc:
        print("FAIL:", exc)

queries = {
    "home_like_unaccepted": """ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата, Т.ПринятаКИсполнению, Т.Исполнитель.Наименование
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И НЕ Т.ПринятаКИсполнению
            И Т.Исполнитель = &П
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "home_like_all_mine": """ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата, Т.ПринятаКИсполнению, Т.Исполнитель.Наименование
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель = &П
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "by_user_catalog": """ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель В (
                ВЫБРАТЬ Ссылка ИЗ Справочник.Пользователи ГДЕ Наименование = &Имя)
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
}

print("\n=== Queries with user ref ===")
for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        query = app.NewObject("Query", q)
        if "&П" in q:
            query.SetParameter("П", user)
        if "&Имя" in q:
            query.SetParameter("Имя", user.ПолноеИмя)
        t = query.Execute().Unload()
        print("rows:", t.Count())
        for i in range(min(15, t.Count())):
            row = t.Get(i)
            print(
                f"  {getattr(row, 'Номер', '')} | {str(getattr(row, 'Дата', ''))[:16]} | "
                f"{str(getattr(row, 'Наименование', ''))[:65]}"
            )
    except Exception as exc:
        print("FAIL:", exc)

# Try common module names for start page
for mod in ("ОбщегоНазначения", "ИнтеграцияС1СДокументооборот", "УправлениеДоступом"):
    try:
        m = getattr(app, mod)
        print(f"\nmodule {mod}: OK", type(m))
    except Exception:
        pass
