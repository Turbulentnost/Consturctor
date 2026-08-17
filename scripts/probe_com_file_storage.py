"""Probe file storage volume and binary data access."""
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
    """ВЫБРАТЬ
        Ф.Ссылка, Ф.Наименование, Ф.Расширение, Ф.Размер,
        Ф.ТипХраненияФайла, Ф.ПутьКФайлу,
        Ф.Том.Наименование КАК VolName,
        Ф.Том.ПолныйПутьWindows КАК VolPath,
        Ф.Том.ПолныйПутьLinux КАК VolPathLinux,
        Ф.ФайлХранилище КАК StorageFile
        ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref""",
)
fq.SetParameter("Ref", doc)
frow = fq.Execute().Unload().Get(0)
file_ref = frow.Ссылка
print("file ref ok")
for col in (
    "Наименование", "Расширение", "Размер", "ТипХраненияФайла", "ПутьКФайлу",
    "VolName", "VolPath", "VolPathLinux", "StorageFile",
):
    print(f"  {col}:", getattr(frow, col, ""))

# versions catalog
print("\n=== ВерсииФайлов ===")
try:
    vq = app.NewObject(
        "Query",
        """ВЫБРАТЬ ПЕРВЫЕ 5
            В.Ссылка, В.НомерВерсии, В.Размер, В.Том.ПолныйПутьWindows, В.ПутьКФайлу, В.ТипХраненияФайла
            ИЗ Справочник.ВерсииФайлов КАК В
            ГДЕ В.Владелец = &Ref
            УПОРЯДОЧИТЬ ПО В.НомерВерсии УБЫВ""",
    )
    vq.SetParameter("Ref", file_ref)
    vt = vq.Execute().Unload()
    print("versions:", vt.Count())
    for i in range(vt.Count()):
        vr = vt.Get(i)
        print(
            " ",
            getattr(vr, "НомерВерсии", ""),
            getattr(vr, "Размер", ""),
            getattr(vr, "ПолныйПутьWindows", ""),
            getattr(vr, "ПутьКФайлу", ""),
        )
except Exception as exc:
    print("FAIL:", exc)

# try binary from storage register
print("\n=== storage registers ===")
for reg in (
    "ХранилищеФайлов",
    "ДвоичныеДанныеФайлов",
    "ПрисоединенныеФайлы",
):
    q = f"ВЫБРАТЬ ПЕРВЫЕ 1 * ИЗ РегистрСведений.{reg}"
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        cols = [t.Columns.Get(i).Name for i in range(t.Columns.Count())]
        print(f"OK {reg}: cols={cols[:10]}")
    except Exception as exc:
        print(f"NO {reg}: {str(exc)[:100]}")

# EvalExpr for enum storage type
print("\n=== storage enum ===")
try:
    st = frow.ТипХраненияФайла
    print("enum str:", app.String(st))
except Exception as exc:
    print("enum fail:", exc)

# Try ПолучитьИмяФайла with volume path composed manually
vol_path = str(getattr(frow, "VolPath", "") or "")
rel_path = str(getattr(frow, "ПутьКФайлу", "") or "")
if vol_path and rel_path:
    full = Path(vol_path) / rel_path
    print("\ncomposed path:", full, "exists:", full.is_file())

# Try common module for data
print("\n=== module calls ===")
for mod_name, method in (
    ("РаботаСФайламиСлужебный", "ДанныеФайла"),
    ("РаботаСФайламиСлужебный", "ПолучитьДанныеФайла"),
    ("РаботаСФайламиСлужебныйВызовСервера", "ДанныеФайла"),
    ("РаботаСФайламиСлужебныйВызовСервера", "ПолучитьДанныеФайла"),
):
    try:
        mod = getattr(app, mod_name)
        fn = getattr(mod, method)
        data = fn(file_ref)
        print(f"OK {mod_name}.{method}: {type(data)}")
        if hasattr(data, "Получить"):
            b = bytes(data.Получить())
            print("  len", len(b), "head", b[:20])
    except Exception as exc:
        print(f"FAIL {mod_name}.{method}: {str(exc)[:140]}")
