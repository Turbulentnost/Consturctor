"""Find and call МоиЗадачи in 1C ERP via COM."""
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
user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
print("user:", user.ПолноеИмя)

# 1) direct global module / processing names
names = [
    "МоиЗадачи",
    "МоиЗадачиСервер",
    "МоиЗадачиКлиент",
    "МоиЗадачиВызовСервера",
    "МоиЗадачиПереопределяемый",
    "РаботаСМоимиЗадачами",
    "УправлениеМоимиЗадачами",
]
for name in names:
    try:
        obj = getattr(app, name)
        print("FOUND module:", name, type(obj))
    except Exception:
        pass

# 2) metadata search
print("\n=== Metadata search: *МоиЗадачи* ===")
try:
    md = app.Metadata
except Exception:
    md = app.Metadata()
for coll_attr, label in (
    ("DataProcessors", "DataProcessor"),
    ("Reports", "Report"),
    ("CommonModules", "CommonModule"),
    ("Catalogs", "Catalog"),
    ("InformationRegisters", "InformationRegister"),
):
    coll = getattr(md, coll_attr)
    hits = []
    for i in range(coll.Count()):
        item = coll.Get(i)
        n = item.Name
        if "МоиЗадачи" in n or "МоиЗадач" in n:
            hits.append(n)
    if hits:
        print(label, hits)

# 2b) direct metadata indexer attempts
for path in (
    "Reports.МоиЗадачи",
    "DataProcessors.МоиЗадачи",
    "CommonModules.МоиЗадачи",
    "CommonForms.МоиЗадачи",
    "Catalogs.МоиЗадачи",
):
    print(f"\n=== Try {path} ===")
    try:
        parts = path.split(".")
        obj = app
        for p in parts:
            obj = obj[p]
        print("OK", type(obj))
    except Exception as exc:
        print("FAIL", str(exc)[:120])

# 3) try open processing/report by name
for proc in ("МоиЗадачи",):
    print(f"\n=== Try DataProcessors.{proc} ===")
    try:
        dp = app.DataProcessors[proc]
        print("DataProcessor OK:", dp)
        for m in ("Create", "ПолучитьМакет", "ПолучитьФорму", "ПолучитьСписокЗадач", "Сформировать"):
            try:
                fn = getattr(dp, m)
                print(" method exists:", m)
            except Exception:
                pass
        try:
            obj = dp.Create()
            print("Create OK:", type(obj))
            for m in (
                "ПолучитьСписокЗадач",
                "Сформировать",
                "ПолучитьДанные",
                "Задачи",
                "ТекстЗапроса",
                "СформироватьСписок",
            ):
                try:
                    fn = getattr(obj, m)
                    print("  obj method:", m)
                    try:
                        r = fn()
                        print("   call ->", type(r), str(r)[:120])
                    except Exception as exc:
                        print("   call fail:", str(exc)[:120])
                except Exception:
                    pass
        except Exception as exc:
            print("Create FAIL:", exc)
    except Exception as exc:
        print("DataProcessor FAIL:", exc)

# 4) query objects containing МоиЗадачи in query text via common modules
for mod_name in ("МоиЗадачи", "МоиЗадачиСервер", "БизнесПроцессыИЗадачиСервер"):
    print(f"\n=== Module methods {mod_name} ===")
    try:
        mod = getattr(app, mod_name)
    except Exception as exc:
        print("missing", exc)
        continue
    for method in (
        "СписокЗадач",
        "ПолучитьСписокЗадач",
        "ЗадачиПользователя",
        "Сформировать",
        "ТекущиеЗадачи",
        "ДанныеФормы",
        "ПриСозданииНаСервере",
        "ПолучитьЗадачи",
        "МоиЗадачи",
    ):
        try:
            fn = getattr(mod, method)
            print(" method:", method)
            for args in ([], [user]):
                try:
                    r = fn(*args) if args else fn()
                    if hasattr(r, "Unload"):
                        t = r.Unload()
                        print(f"  args={args} rows={t.Count()}")
                        for i in range(min(15, t.Count())):
                            row = t.Get(i)
                            cols = [t.Columns.Get(c).Name for c in range(min(5, t.Columns.Count()))]
                            vals = [str(getattr(row, c, ""))[:50] for c in cols]
                            print("   ", " | ".join(vals))
                    else:
                        print(f"  args={args} ->", type(r), str(r)[:120])
                    break
                except Exception as exc:
                    if args:
                        print(f"  args={args} fail:", str(exc)[:100])
        except Exception:
            pass
