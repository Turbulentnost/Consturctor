"""Search 1C metadata for «Начальная страница» / start page."""
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
md = app.Metadata

patterns = ("Начальн", "Стартов", "РабочийСтол", "MainPage", "HomePage", "StartPage")

print("=== Поиск «Начальная страница» в метаданных ===\n")
for coll_name in (
    "Subsystems",
    "CommonForms",
    "CommonCommands",
    "DataProcessors",
    "Reports",
    "CommonModules",
    "CommonPictures",
    "Roles",
):
    coll = getattr(md, coll_name, None)
    if coll is None:
        continue
    hits: list[str] = []
    for i in range(coll.Count()):
        obj = coll.Get(i)
        name = obj.Name
        syn = ""
        try:
            syn = str(getattr(obj, "Synonym", "") or "")
        except Exception:
            pass
        if any(p.lower() in name.lower() for p in patterns) or any(
            p.lower() in syn.lower() for p in ("начальн", "стартов", "рабоч")
        ):
            hits.append(f"{name}" + (f" — {syn}" if syn and syn != name else ""))
    if hits:
        print(f"{coll_name}:")
        for h in hits:
            print(f"  {h}")
        print()

# Exact name search
print("=== Точные совпадения в имени ===")
exact = ("НачальнаяСтраница", "НачальнаяСтраницаСистемы", "СтартоваяСтраница", "РабочийСтол")
for coll_name in ("CommonForms", "DataProcessors", "Subsystems", "CommonModules"):
    coll = getattr(md, coll_name)
    for target in exact:
        try:
            obj = coll[target]
            syn = str(getattr(obj, "Synonym", "") or "")
            print(f"OK {coll_name}.{target} — {syn}")
        except Exception:
            pass

print("\n=== Подсистема ТД_Документооборот (ваш модуль) ===")
try:
    sub = md.Subsystems.ТД_Документооборот
    print("Name:", sub.Name, "| Synonym:", getattr(sub, "Synonym", ""))
except Exception as exc:
    print("FAIL:", exc)

print("\n=== CommonForms с «Начальн» или «Задач» (Документооборот) ===")
cf = md.CommonForms
for i in range(cf.Count()):
    obj = cf.Get(i)
    name = obj.Name
    syn = str(getattr(obj, "Synonym", "") or "")
    if "Начальн" in name or "Начальн" in syn or (
        "Задач" in name and ("Документооборот" in name or "ДО" in name)
    ):
        print(f"  {name} — {syn}")
