"""Deep query incoming doc НП00-004286 for any readable text."""
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

queries = {
    "doc_full": f"""ВЫБРАТЬ
        Д.Номер, Д.Дата, Д.Комментарий, Д.Содержание, Д.ТекстHTML,
        Д.ТемаСлужебнойЗаписки, Д.EmailОтправителяПисьма, Д.EmailПолучателяПисьма,
        Д.Кому, Д.НомерИсходящий, Д.ДатаИсходящая, Д.Контрагент.Наименование,
        Д.Партнер.Наименование, Д.Ответственный.Наименование, Д.Статус,
        Д.ИсточникПоступления, Д.Направление, Д.ID_XML
        ИЗ Документ.ТД_ВходящаяКорреспонденция КАК Д
        ГДЕ Д.Номер = "{num}\"""",
    "file_info": f"""ВЫБРАТЬ
        Ф.Наименование, Ф.Расширение, Ф.Размер, Ф.Описание, Ф.Автор.Наименование,
        Ф.ДатаСоздания, Ф.ДатаМодификацииУниверсальная, Ф.ПутьКФайлу,
        Ф.Том.Наименование, Ф.Том.ПолныйПутьWindows, Ф.ТипХраненияФайла,
        Ф.СтатусИзвлеченияТекста, Ф.ТекстХранилище
        ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ВладелецФайла.Номер = "{num}\"""",
}

for name, q in queries.items():
    print(f"\n=== {name} ===")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print("rows", t.Count())
        if not t.Count():
            continue
        row = t.Get(0)
        cols = [t.Columns.Get(i).Name for i in range(t.Columns.Count())]
        for col in cols:
            val = getattr(row, col, None)
            if val is None or val is False:
                continue
            if hasattr(val, "Наименование"):
                val = val.Наименование
            elif hasattr(val, "Имя"):
                try:
                    val = app.String(val)
                except Exception:
                    val = str(val)
            text = str(val).strip()
            if not text or text.startswith("0001-01-01") or text == "<COMObject <unknown>>":
                continue
            print(f"  {col}: {text[:2000]}")
    except Exception as exc:
        print("FAIL", str(exc)[:250])

# Try ПолучитьДанныеФайла with extra args
print("\n=== binary attempts with args ===")
fq = app.NewObject(
    "Query",
    f'ВЫБРАТЬ Ф.Ссылка ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф ГДЕ Ф.ВладелецФайла.Номер = "{num}"',
)
file_ref = fq.Execute().Unload().Get(0).Ссылка
svc = app.РаботаСФайламиСлужебныйВызовСервера
for args in [
    (file_ref,),
    (file_ref, True),
    (file_ref, False, True),
    (file_ref, True, True),
]:
    try:
        r = svc.ПолучитьДанныеФайла(*args)
        print("args", args, "->", getattr(r, "ИмяФайла", ""), getattr(r, "Размер", ""), "has Данные", hasattr(r, "Данные"))
    except Exception as exc:
        print("args", args, "FAIL", str(exc)[:120])
