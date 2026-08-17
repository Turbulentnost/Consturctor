"""Try server-side binary retrieval for attached file."""
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

num = "НП00-004286"
doc = (
    app.NewObject(
        "Query",
        f'ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка ИЗ Документ.ТД_ВходящаяКорреспонденция КАК Д ГДЕ Д.Номер = "{num}"',
    )
    .Execute()
    .Unload()
    .Get(0)
    .Ссылка
)
fq = app.NewObject(
    "Query",
    """ВЫБРАТЬ Ф.Ссылка ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref""",
)
fq.SetParameter("Ref", doc)
file_ref = fq.Execute().Unload().Get(0).Ссылка

modules = [
    "РаботаСФайлами",
    "РаботаСФайламиСлужебный",
    "РаботаСФайламиСлужебныйВызовСервера",
    "РаботаСФайламиКлиент",
    "РаботаСФайламиКлиентСервер",
    "РаботаСФайламиВызовСервера",
]
methods = [
    "ДанныеФайла",
    "ПолучитьДанныеФайла",
    "ПолучитьДвоичныеДанныеФайла",
    "ПолучитьДанныеФайлаДляАдминистратора",
    "ВыгрузитьФайл",
    "СохранитьФайл",
    "ПолучитьФайл",
    "ПолучитьНавигационнуюСсылку",
    "ПолучитьАдресВременногоХранилищаФайла",
    "ПоместитьФайлВХранилище",
]

print("=== method matrix ===")
for mod_name in modules:
    try:
        mod = getattr(app, mod_name)
    except Exception:
        continue
    hits = [m for m in dir(mod) if not m.startswith("_") and any(x in m for x in ("Данн", "Выгруз", "Сохран", "Получ", "Файл"))]
    if hits:
        print(f"\n{mod_name}:")
        for m in sorted(hits)[:25]:
            print(" ", m)

print("\n=== invoke attempts ===")
for mod_name in modules:
    try:
        mod = getattr(app, mod_name)
    except Exception:
        continue
    for method in methods:
        if not hasattr(mod, method):
            continue
        fn = getattr(mod, method)
        try:
            if method == "ВыгрузитьФайл":
                r = fn(file_ref, r"C:\Temp\onec_out.msg")
            elif method in ("СохранитьФайл",):
                r = fn(file_ref, app.КаталогВременныхФайлов())
            else:
                r = fn(file_ref)
            print(f"OK {mod_name}.{method} -> {type(r)} {str(r)[:100]}")
            if hasattr(r, "Получить"):
                b = bytes(r.Получить())
                print(f"   bytes={len(b)}")
        except Exception as exc:
            msg = str(exc)
            if "Не удалось открыть файл" in msg or "Недостаточно прав" in msg:
                print(f"DENY {mod_name}.{method}: {msg[:120]}")
            elif "method" not in msg.lower():
                print(f"FAIL {mod_name}.{method}: {msg[:120]}")

# Try UNC read anyway
print("\n=== UNC direct ===")
unc = Path(r"\\srv2\erp_file\20200909") / "НП00-004286.msg"
try:
    print("exists", unc.exists(), "size", unc.stat().st_size if unc.exists() else "-")
except Exception as exc:
    print("UNC fail:", exc)

# OData file entity probe
print("\n=== OData ===")
import base64
import json
import urllib.request

base = env["ODATA_BASE_URL"].rstrip("/")
auth = base64.b64encode(f"{env['ODATA_USERNAME']}:{env['ODATA_PASSWORD']}".encode()).decode()
# find file by owner
for entity in (
    "Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы",
    "Document_ТД_ВходящаяКорреспонденция",
):
    url = f"{base}/{entity}?$top=1&$format=json"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        print(entity, "OK", list((data.get("value") or [{}])[0].keys())[:8])
    except Exception as exc:
        print(entity, "FAIL", exc)

# filter attached file by description/name
url = (
    f"{base}/Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы?"
    f"$filter=Description eq '{num}' or FileName eq '{num}.msg'&$top=5&$format=json"
)
req = urllib.request.Request(url, headers={"Authorization": f"Basic {auth}"})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    print("OData filter hits:", len(data.get("value") or []))
    for item in data.get("value") or []:
        print(" keys:", list(item.keys())[:15])
        for k in ("Ref_Key", "Description", "FileName", "Size", "BinaryData", "FileStorageType"):
            if k in item:
                print(f"  {k}:", str(item[k])[:80])
except Exception as exc:
    print("OData filter FAIL:", exc)
