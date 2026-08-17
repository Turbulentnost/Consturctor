import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
env = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("="); env[k.strip()] = v.strip().strip('"').strip("'")
import win32com.client
conn = f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
num = "НП00-004286"
doc = app.NewObject("Query", f'ВЫБРАТЬ ПЕРВЫЕ 1 Д.Ссылка ИЗ Документ.ТД_ВходящаяКорреспонденция КАК Д ГДЕ Д.Номер = "{num}"').Execute().Unload().Get(0).Ссылка
fq = app.NewObject("Query", "ВЫБРАТЬ Ф.Ссылка ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф ГДЕ Ф.ВладелецФайла = &Ref")
fq.SetParameter("Ref", doc)
file_ref = fq.Execute().Unload().Get(0).Ссылка
svc = app.РаботаСФайламиСлужебныйВызовСервера
for method in ("ДанныеФайла", "ПолучитьДанныеФайла"):
    print("\n===", method, "===")
    result = getattr(svc, method)(file_ref)
    print("repr:", result)
    # try as structure via property access common in 1C
    for key in (
        "Данные", "Data", "Имя", "Name", "Расширение", "Extension",
        "ИмяФайла", "FileName", "Размер", "Size", "Ссылка", "Ref",
        "Адрес", "Address", "ДвоичныеДанные", "BinaryData", "Текст", "Text",
        "ПолноеИмя", "FullName", "Хранение", "Storage",
    ):
        try:
            val = getattr(result, key)
            print(f"  {key}: {type(val)} {str(val)[:120]}")
            if hasattr(val, "Получить"):
                b = bytes(val.Получить())
                print(f"    -> bytes len={len(b)} head={b[:30]!r}")
        except Exception:
            pass
    # try indexing like COM SafeArray / structure
    try:
        cnt = result.Count()
        print(" Count:", cnt)
        for i in range(min(10, cnt)):
            print(" ", i, result.Get(i))
    except Exception:
        pass
