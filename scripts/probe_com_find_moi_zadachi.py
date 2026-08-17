"""Scan 1C metadata for objects related to МоиЗадачи."""
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
md = app.Metadata

patterns = ("МоиЗадачи", "МоиЗадач", "MyTask", "MyTasks", "ЗадачиПользов")

for coll_name in (
    "Reports",
    "DataProcessors",
    "CommonModules",
    "CommonForms",
    "Catalogs",
    "InformationRegisters",
    "Subsystems",
    "Roles",
    "ScheduledJobs",
):
    coll = getattr(md, coll_name)
    hits = []
    for i in range(coll.Count()):
        name = coll.Get(i).Name
        if any(p.lower() in name.lower() for p in patterns):
            hits.append(name)
    print(f"{coll_name}: {hits if hits else '-'}")

# direct access attempts
candidates = [
    "Reports",
    "DataProcessors",
    "CommonModules",
    "CommonForms",
]
object_names = [
    "МоиЗадачи",
    "МоиЗадачиСервер",
    "МоиЗадачиКлиент",
    "МоиЗадачиВызовСервера",
    "ЗадачиМне",
    "СписокМоихЗадач",
]

print("\n=== Direct access ===")
for coll_name in candidates:
    coll = getattr(app, coll_name)
    for obj_name in object_names:
        for getter in (
            lambda: getattr(coll, obj_name),
            lambda: coll[obj_name],
        ):
            try:
                obj = getter()
                print(f"OK app.{coll_name}.{obj_name} -> {type(obj)}")
                if coll_name == "DataProcessors" and obj_name == "МоиЗадачи":
                    inst = obj.Create()
                    print("  Create ->", type(inst))
                    for m in dir(inst):
                        if "задач" in m.lower() or "task" in m.lower() or "спис" in m.lower():
                            print("   method?", m)
                if coll_name == "Reports" and obj_name == "МоиЗадачи":
                    inst = obj.Create()
                    print("  Report Create ->", type(inst))
            except Exception:
                pass

# search in subsystem / predefined names via query to config (if any)
print("\n=== Query config names ===")
q = """ВЫБРАТЬ ПЕРВЫЕ 50
    Объекты.Имя КАК Имя, Объекты.Синоним КАК Синоним
    ИЗ (ВЫБРАТЬ \"Reports\" КАК Имя) КАК Объекты"""
# fallback: scan common module names containing Задач from metadata all CommonModules
all_task_modules = []
cm = md.CommonModules
for i in range(cm.Count()):
    n = cm.Get(i).Name
    if "Задач" in n:
        all_task_modules.append(n)
print("CommonModules with Задач:", all_task_modules[:40], "total", len(all_task_modules))

for mod_name in all_task_modules:
    if "Мои" in mod_name or "Пользовател" in mod_name or "Текущ" in mod_name:
        print(f"\nTry module {mod_name}")
        try:
            mod = getattr(app, mod_name)
            for method in ("ПолучитьСписокЗадач", "ЗадачиПользователя", "Сформировать", "ТекущиеЗадачи", "МоиЗадачи"):
                try:
                    fn = getattr(mod, method)
                    print("  has", method)
                except Exception:
                    pass
        except Exception as exc:
            print("  fail", exc)
