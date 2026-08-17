"""Read extracted text from ТекстХранилище for attached file."""
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

q = f"""ВЫБРАТЬ
    Ф.Наименование, Ф.Расширение, Ф.СтатусИзвлеченияТекста,
    Ф.ТекстХранилище, Ф.ТекстХранилище.Наименование КАК TextStoreName
    ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф
    ГДЕ Ф.ВладелецФайла.Номер = "{num}\""""
t = app.NewObject("Query", q).Execute().Unload()
print("files", t.Count())
for i in range(t.Count()):
    r = t.Get(i)
    print("\nfile", getattr(r, "Наименование", ""))
    try:
        st = getattr(r, "СтатусИзвлеченияТекста", None)
        print(" status:", app.String(st) if st else st)
    except Exception as exc:
        print(" status err:", exc)
    ts = getattr(r, "ТекстХранилище", None)
    print(" text store ref:", ts)
    print(" text store name:", getattr(r, "TextStoreName", ""))
    if ts:
        try:
            md = ts.Метаданные().Имя
            print(" text store type:", md)
        except Exception as exc:
            print(" md err:", exc)
        try:
            obj = ts.ПолучитьОбъект()
            for attr in ("Текст", "Text", "Наименование", "Description", "Данные", "Value"):
                try:
                    val = getattr(obj, attr, None)
                    if val:
                        print(f"  {attr}:", str(val)[:5000])
                except Exception:
                    pass
        except Exception as exc:
            print(" object err:", exc)

# registers with text
for reg in ("ТекстовыеДанные", "ТекстовыеДанныеФайлов", "ХранилищеТекстов", "ТекстыФайлов"):
    try:
        qq = f"ВЫБРАТЬ ПЕРВЫЕ 1 * ИЗ РегистрСведений.{reg}"
        rt = app.NewObject("Query", qq).Execute().Unload()
        print("register OK", reg, [rt.Columns.Get(i).Name for i in range(rt.Columns.Count())][:8])
    except Exception as exc:
        print("register NO", reg, str(exc)[:80])
