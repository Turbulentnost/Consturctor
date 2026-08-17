"""Probe 1C COM attachment APIs for a task reference."""
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

import win32com.client

conn = (
    f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";'
    f'Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
)
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)

number = "00-Л-000039079"
q = f"""ВЫБРАТЬ ПЕРВЫЕ 1
    Т.Ссылка КАК Ref,
    Т.Предмет КАК Subject,
    Т.БизнесПроцесс КАК BP
    ИЗ Задача.ЗадачаИсполнителя КАК Т
    ГДЕ Т.Номер = "{number}\""""
row = app.NewObject("Query", q).Execute().Unload().Get(0)
ref = row.Ref
subject = row.Subject
bp = row.BP
print("ref:", ref)
print("subject type:", type(subject), subject)
print("bp:", bp)

try:
    subj_type = str(subject.Метаданные().Имя) if subject else ""
    print("subject metadata:", subj_type)
    print("subject number:", getattr(subject, "Номер", ""))
    print("subject name:", getattr(subject, "Наименование", ""))
except Exception as exc:
    print("subject parse fail:", exc)

# List global managers with 'Файл' in name
print("\nManagers with 'Файл':")
for name in dir(app):
    if "айл" in name or "File" in name:
        print(" ", name)

# Try РаботаСФайлами variants
for mgr_name in ("РаботаСФайлами", "РаботаСФайламиКлиент", "РаботаСФайламиСлужебный"):
    if not hasattr(app, mgr_name):
        continue
    mgr = getattr(app, mgr_name)
    print(f"\n=== {mgr_name} methods (file-related) ===")
    for m in dir(mgr):
        if "рисоед" in m.lower() or "file" in m.lower() or "Файл" in m:
            print(" ", m)

# Try attached files on task ref
for target_name, target in (("task", ref), ("subject", subject), ("bp", bp)):
    if target is None:
        continue
    print(f"\n--- attachments for {target_name} ---")
    try:
        mgr = app.РаботаСФайлами
        for method in (
            "ПолучитьПрисоединенныеФайлы",
            "ПолучитьВсеПодчиненныеФайлы",
            "ПолучитьФайлы",
        ):
            if not hasattr(mgr, method):
                continue
            fn = getattr(mgr, method)
            try:
                result = fn(target)
                cnt = result.Count() if hasattr(result, "Count") else "?"
                print(f"  {method}: count={cnt}")
                if hasattr(result, "Count") and result.Count():
                    f0 = result.Get(0)
                    print(f"    sample: {getattr(f0, 'Наименование', f0)} ext={getattr(f0, 'Расширение', '')}")
            except Exception as exc:
                print(f"  {method}: FAIL {str(exc)[:120]}")
    except Exception as exc:
        print("  mgr fail:", exc)

# Metadata: catalogs/registers with files
md = app.Metadata
print("\nMetadata catalogs with 'Файл':")
for i in range(md.Catalogs.Count()):
    n = md.Catalogs.Get(i).Name
    if "айл" in n:
        print(" ", n)

print("\nMetadata registers with 'Файл':")
for i in range(md.InformationRegisters.Count()):
    n = md.InformationRegisters.Get(i).Name
    if "айл" in n or "рисоед" in n:
        print(" ", n)
