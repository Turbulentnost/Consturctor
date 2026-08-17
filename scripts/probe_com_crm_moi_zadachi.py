"""Deep search: Мои*, CRM tasks register, start page forms."""
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
fio = env["ERP_LOGIN"]
md = app.Metadata

print("=== Metadata names containing 'Мои' ===")
for coll_name in (
    "Reports", "DataProcessors", "CommonModules", "CommonForms",
    "Catalogs", "InformationRegisters", "Documents", "Enums", "Subsystems",
):
    coll = getattr(md, coll_name)
    hits = [coll.Get(i).Name for i in range(coll.Count()) if "Мои" in coll.Get(i).Name]
    if hits:
        print(coll_name, hits)

print("\n=== Metadata *Задач* in CommonForms/Reports/DataProcessors ===")
for coll_name in ("CommonForms", "Reports", "DataProcessors"):
    coll = getattr(md, coll_name)
    hits = [coll.Get(i).Name for i in range(coll.Count()) if "Задач" in coll.Get(i).Name]
    if hits:
        print(coll_name, hits[:30])

# CRM register
print("\n=== CRM_ЗадачиПользователей ===")
queries = {
    "crm_all": """ВЫБРАТЬ ПЕРВЫЕ 20
        Р.Пользователь.Наименование, Р.Задача.Наименование, Р.Задача.Номер, Р.Задача.Дата
        ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
        УПОРЯДОЧИТЬ ПО Р.Задача.Дата УБЫВ""",
    "crm_mine": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Р.Задача.Номер, Р.Задача.Наименование, Р.Задача.Дата, Р.Задача.Выполнена
        ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
        ГДЕ Р.Пользователь.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Р.Задача.Дата УБЫВ""",
    "crm_mine_open": f"""ВЫБРАТЬ ПЕРВЫЕ 30
        Р.Задача.Номер, Р.Задача.Наименование, Р.Задача.Дата
        ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
        ГДЕ Р.Пользователь.Наименование = "{fio.replace('"', '""')}"
            И НЕ Р.Задача.Выполнена
        УПОРЯДОЧИТЬ ПО Р.Задача.Дата УБЫВ""",
}
for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print("rows:", t.Count())
        for i in range(min(20, t.Count())):
            row = t.Get(i)
            vals = []
            for cname in ("Номер", "Наименование", "Дата", "Пользователь"):
                v = getattr(row, cname, None)
                if v not in (None, ""):
                    vals.append(f"{cname}={str(v)[:55]}")
            print(" ", " | ".join(vals) if vals else row)
    except Exception as exc:
        print("FAIL", str(exc)[:180])

# CRM modules
print("\n=== CRM modules ===")
cm = md.CommonModules
crm_mods = [cm.Get(i).Name for i in range(cm.Count()) if cm.Get(i).Name.startswith("CRM")]
print("count", len(crm_mods))
for n in crm_mods:
    if "Задач" in n or "Мои" in n or "Текущ" in n:
        print(" ", n)
        try:
            mod = getattr(app, n)
            for m in ("ПолучитьЗадачи", "МоиЗадачи", "ЗадачиПользователя", "СписокЗадач", "ТекущиеЗадачи"):
                try:
                    getattr(mod, m)
                    print("    has", m)
                except Exception:
                    pass
        except Exception as exc:
            print("    access fail", exc)

# Try Reports / DP with Задачи in name
print("\n=== Open task-related processors/reports ===")
for coll_name, factory in (("DataProcessors", "Create"), ("Reports", "Create")):
    coll = getattr(md, coll_name)
    for i in range(coll.Count()):
        name = coll.Get(i).Name
        if "Задач" not in name and "Мои" not in name:
            continue
        print(f"try {coll_name}.{name}")
        try:
            meta = getattr(md, coll_name)[name]
            obj = getattr(app, coll_name)[name].Create()
            print("  created", type(obj))
        except Exception as exc:
            print("  fail", str(exc)[:100])
