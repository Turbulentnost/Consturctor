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
result = app.РаботаСФайламиСлужебныйВызовСервера.ПолучитьДанныеФайла(file_ref)
print("Count", result.Count())
for i in range(result.Count()):
    try:
        item = result.Get(i)
        print(i, type(item), str(item)[:100])
    except Exception as exc:
        print(i, "ERR", exc)
# also try property names from 1C structure - often accessible by Russian names directly
for key in (
    "Данные", "ДвоичныеДанные", "Текст", "Base64", "Location", "Адрес",
    "ХранилищеДвоичныхДанных", "ХранилищеЗначения", "АдресВременногоХранилища",
):
    try:
        val = getattr(result, key)
        print(f"KEY {key}:", type(val), str(val)[:80])
        if hasattr(val, "Получить"):
            b = bytes(val.Получить())
            print("  bytes", len(b))
    except Exception as exc:
        print(f"KEY {key} missing")
