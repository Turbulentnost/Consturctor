"""Read attachment bytes via РаботаСФайламиСлужебныйВызовСервера."""
from __future__ import annotations

import sys
import tempfile
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
    """ВЫБРАТЬ Ф.Ссылка, Ф.Наименование, Ф.Расширение ИЗ Справочник.ТД_ВходящаяКорреспонденцияПрисоединенныеФайлы КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref""",
)
fq.SetParameter("Ref", doc)
frow = fq.Execute().Unload().Get(0)
file_ref = frow.Ссылка
print("file:", frow.Наименование, frow.Расширение)

svc = app.РаботаСФайламиСлужебныйВызовСервера
for method in ("ДанныеФайла", "ПолучитьДанныеФайла"):
    print(f"\n=== {method} ===")
    data = getattr(svc, method)(file_ref)
    print("type:", type(data))
    for attr in dir(data):
        if attr.startswith("_"):
            continue
        if any(x in attr.lower() for x in ("получ", "get", "write", "size", "length", "размер")):
            print(" attr:", attr)
    try:
        if hasattr(data, "Получить"):
            b = bytes(data.Получить())
            print("Получить() len:", len(b))
            out = ROOT / "logs" / f"{num}.msg"
            out.write_bytes(b)
            print("saved:", out)
    except Exception as exc:
        print("Получить fail:", exc)
    try:
        if hasattr(data, "Write"):
            tmp = Path(tempfile.gettempdir()) / f"{num}.msg"
            data.Write(str(tmp))
            print("Write ok:", tmp, tmp.stat().st_size)
    except Exception as exc:
        print("Write fail:", exc)
