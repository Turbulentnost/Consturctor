"""Probe 1C COM file read APIs for attached file."""
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
    """ВЫБРАТЬ Ф.Ссылка, Ф.Наименование, Ф.Расширение, Ф.Размер, Ф.ТипХраненияФайла, Ф.ПутьКФайлу, Ф.Том
        ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref""",
)
fq.SetParameter("Ref", doc)
frow = fq.Execute().Unload().Get(0)
file_ref = frow.Ссылка
print("file:", frow.Наименование, frow.Расширение, frow.Размер)
print("storage:", frow.ТипХраненияФайла)
print("path:", frow.ПутьКФайлу)
print("volume:", frow.Том)

print("\nРаботаСФайлами methods:")
mgr = app.РаботаСФайлами
methods = [m for m in dir(mgr) if not m.startswith("_")]
for m in sorted(methods):
    if any(x in m for x in ("Данн", "Файл", "Получ", "Выгруз", "Сохран", "Врем", "Двоич", "Текст")):
        print(" ", m)

print("\nTrying methods:")
candidates = [
    "ПолучитьДанныеФайла",
    "ПолучитьДвоичныеДанныеФайла",
    "ДанныеФайла",
    "ПолучитьИмяФайла",
    "ПолучитьИмяФайлаПоСсылке",
    "СохранитьФайлНаДиск",
    "ВыгрузитьФайл",
    "ПолучитьФайл",
    "ПолучитьURLФайла",
]
for method in candidates:
    if not hasattr(mgr, method):
        continue
    fn = getattr(mgr, method)
    try:
        if method in ("ПолучитьИмяФайла", "ПолучитьИмяФайлаПоСсылке"):
            result = fn(file_ref, app.КаталогВременныхФайлов(), 1)
        elif method == "СохранитьФайлНаДиск":
            tmp = str(Path("C:/Temp/onec_probe.msg"))
            result = fn(file_ref, tmp)
        else:
            result = fn(file_ref)
        print(f"  OK {method}: {type(result)} {str(result)[:120]}")
        if hasattr(result, "Получить"):
            data = bytes(result.Получить())
            print(f"    binary len={len(data)} head={data[:40]!r}")
    except Exception as exc:
        print(f"  FAIL {method}: {str(exc)[:160]}")

print("\nFile object fields:")
try:
    obj = file_ref.ПолучитьОбъект()
    for attr in dir(obj):
        if any(x in attr for x in ("Двоич", "Данн", "Текст", "Путь", "Хран", "Файл", "Размер")):
            if attr.startswith("_"):
                continue
            try:
                val = getattr(obj, attr)
                if callable(val):
                    continue
                print(f"  {attr}: {str(val)[:100]}")
            except Exception as exc:
                print(f"  {attr}: ERR {exc}")
except Exception as exc:
    print("object fail:", exc)

print("\nРаботаСФайламиСлужебный:")
try:
    svc = app.РаботаСФайламиСлужебный
    for m in dir(svc):
        if not m.startswith("_") and any(x in m for x in ("Данн", "Получ", "Выгруз", "Двоич")):
            print(" ", m)
except Exception as exc:
    print("no svc:", exc)
