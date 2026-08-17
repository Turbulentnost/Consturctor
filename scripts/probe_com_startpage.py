"""Find tasks shown on ERP start page — DO integration + addressing."""
from __future__ import annotations

import os
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
fio = env["ERP_LOGIN"]
print("user:", fio)

# catalog ref for user
q_user = f"""ВЫБРАТЬ Ссылка, Наименование ИЗ Справочник.Пользователи
    ГДЕ Наименование = "{fio.replace('"', '""')}" ИЛИ Наименование ПОДОБНО "%Жалыбин%"
    И НЕ ПометкаУдаления"""
t = app.NewObject("Query", q_user).Execute().Unload()
user_ref = None
for i in range(t.Count()):
    row = t.Get(i)
    print("catalog user:", getattr(row, "Наименование", ""), getattr(row, "Ссылка", ""))
    if str(getattr(row, "Наименование", "")) == fio:
        user_ref = getattr(row, "Ссылка", None)

queries = {}
if user_ref is not None:
    queries["mine_by_ref"] = ("""ВЫБРАТЬ ПЕРВЫЕ 30
        Т.Номер, Т.Наименование, Т.Дата, Т.ПринятаКИсполнению, Т.Выполнена
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена И Т.Исполнитель = &Исп
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""", {"Исп": user_ref})

queries["mine_unaccepted"] = ("""ВЫБРАТЬ ПЕРВЫЕ 30
    Т.Номер, Т.Наименование, Т.Дата, Т.ПринятаКИсполнению
    ИЗ Задача.ЗадачаИсполнителя КАК Т
    ГДЕ НЕ Т.Выполнена И НЕ Т.ПринятаКИсполнению
        И Т.Исполнитель.Наименование = &Имя
    УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""", {"Имя": fio})

queries["mine_accepted"] = ("""ВЫБРАТЬ ПЕРВЫЕ 30
    Т.Номер, Т.Наименование, Т.Дата
    ИЗ Задача.ЗадачаИсполнителя КАК Т
    ГДЕ НЕ Т.Выполнена И Т.ПринятаКИсполнению
        И Т.Исполнитель.Наименование = &Имя
    УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""", {"Имя": fio})

queries["role_addressing"] = ("""ВЫБРАТЬ ПЕРВЫЕ 30
    Т.Номер, Т.Наименование, Т.Дата
    ИЗ Задача.ЗадачаИсполнителя КАК Т
    ГДЕ НЕ Т.Выполнена
        И Т.Исполнитель.Наименование = &Имя
    УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""", {"Имя": fio})

for name, (q, params) in queries.items():
    print(f"\n=== {name} ===")
    try:
        query = app.NewObject("Query", q)
        for pk, pv in params.items():
            query.SetParameter(pk, pv)
        table = query.Execute().Unload()
        print("rows:", table.Count())
        for i in range(min(20, table.Count())):
            row = table.Get(i)
            print(f"  {getattr(row, 'Номер', '')} | {str(getattr(row, 'Дата', ''))[:16]} | {str(getattr(row, 'Наименование', ''))[:60]}")
    except Exception as exc:
        print("FAIL", exc)

# DO integration
print("\n=== DO integration ===")
do = app.ИнтеграцияС1СДокументооборот
for method in (
    "ПолучитьЗадачи",
    "ПолучитьЗадачиПользователя",
    "ПолучитьСписокЗадач",
    "ЗадачиПользователя",
    "ПолучитьКоличествоЗадач",
):
    try:
        fn = getattr(do, method)
        for args in ([], [fio], [user] if user_ref else []):
            try:
                r = fn(*args) if args else fn()
                print(method, args, "->", type(r), str(r)[:120])
                break
            except Exception as inner:
                print(method, args, "FAIL", inner)
    except Exception as exc:
        print(method, "missing", exc)

# Try common ERP start-page processing via NewObject
for proc in ("ЗадачиПользователя", "УправлениеЗадачами"):
    try:
        p = getattr(app, proc)
        print(f"processing {proc}: OK", type(p))
    except Exception:
        pass

# Metadata: find registers related to tasks
try:
    md = app.Metadata()
    for coll_name in ("InformationRegisters", "Reports", "DataProcessors"):
        coll = getattr(md, coll_name, None)
        if coll is None:
            continue
        hits = []
        for i in range(coll.Count()):
            n = coll.Get(i).Name
            if any(x in n.lower() for x in ("задач", "task", "исполн")):
                hits.append(n)
        if hits:
            print(f"\n{coll_name} hits:", hits[:15])
except Exception as exc:
    print("metadata FAIL", exc)
