"""Alternative paths: doc object text, OData binary, temp storage."""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

import base64
import win32com.client

conn = (
    f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";'
    f'Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
)
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
num = "НП00-004286"

# Document object all fields
row = app.NewObject(
    "Query",
    f'ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка ИЗ Документ.ТД_ВходящаяКорреспонденция КАК Д ГДЕ Д.Номер = "{num}"',
).Execute().Unload().Get(0)
doc_ref = row.Ссылка
obj = doc_ref.ПолучитьОбъект()
print("=== Document object text fields ===")
for attr in (
    "Комментарий", "Содержание", "ТекстHTML", "ТемаСлужебнойЗаписки",
    "EmailОтправителяПисьма", "EmailПолучателяПисьма", "Кому", "НомерИсходящий",
):
    try:
        val = getattr(obj, attr, "")
        text = str(val).strip()
        if text and not text.startswith("0001-01-01"):
            print(f"\n{attr} ({len(text)} chars):")
            print(text[:3000])
    except Exception as exc:
        print(attr, "ERR", exc)

# file ref + temp storage
fq = app.NewObject(
    "Query",
    "ВЫБРАТЬ Ф.Ссылка ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф ГДЕ Ф.ВладелецФайла = &Ref",
)
fq.SetParameter("Ref", doc_ref)
file_ref = fq.Execute().Unload().Get(0).Ссылка

print("\n=== temp storage / nav link ===")
for mod_name, method in (
    ("РаботаСФайлами", "ПолучитьНавигационнуюСсылку"),
    ("РаботаСФайлами", "ПолучитьАдресВременногоХранилищаФайла"),
    ("РаботаСФайламиСлужебныйВызовСервера", "ПолучитьАдресВременногоХранилищаФайла"),
    ("РаботаСФайламиСлужебный", "ПолучитьАдресВременногоХранилищаФайла"),
):
    try:
        mod = getattr(app, mod_name)
        if not hasattr(mod, method):
            continue
        val = getattr(mod, method)(file_ref)
        print(f"OK {mod_name}.{method}: {val}")
    except Exception as exc:
        print(f"FAIL {mod_name}.{method}: {str(exc)[:120]}")

# OData: get doc by number then attached files
print("\n=== OData ===")
base = env["ODATA_BASE_URL"].rstrip("/")
auth = base64.b64encode(f"{env['ODATA_USERNAME']}:{env['ODATA_PASSWORD']}".encode()).decode()
headers = {"Authorization": f"Basic {auth}"}

entity = "Catalog_ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы"
url = f"{base}/{urllib.parse.quote(entity, safe='')}" + "?$top=3&$format=json"
req = urllib.request.Request(url, headers=headers)
with urllib.request.urlopen(req, timeout=60) as resp:
    sample = json.loads(resp.read())
print("catalog sample keys:", list((sample.get("value") or [{}])[0].keys())[:20])

# filter by owner - first get doc ref key via OData
entity_doc = "Document_ТД_ВходящаяКорреспонденция"
filter_q = urllib.parse.quote(f"Number eq '{num}'")
url_doc = f"{base}/{urllib.parse.quote(entity_doc, safe='')}" + f"?$filter={filter_q}&$format=json"
req_doc = urllib.request.Request(url_doc, headers=headers)
with urllib.request.urlopen(req_doc, timeout=60) as resp:
    docs = json.loads(resp.read()).get("value") or []
print("doc hits:", len(docs))
if docs:
    ref_key = docs[0].get("Ref_Key")
    print("Ref_Key:", ref_key)
    filter_files = urllib.parse.quote(f"Owner_Key eq guid'{ref_key}'")
    url_files = f"{base}/{urllib.parse.quote(entity, safe='')}" + f"?$filter={filter_files}&$format=json"
    req_files = urllib.request.Request(url_files, headers=headers)
    with urllib.request.urlopen(req_files, timeout=60) as resp:
        files = json.loads(resp.read()).get("value") or []
    print("files:", len(files))
    for f in files:
        print(" file keys:", list(f.keys()))
        for k, v in f.items():
            if k.lower().endswith("data") or "binary" in k.lower() or k in ("FileName", "Description", "Size", "Ref_Key"):
                print(f"  {k}: {str(v)[:100]}")
