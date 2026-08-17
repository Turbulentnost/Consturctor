"""Query CRM attached files for task subject."""
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
row = (
    app.NewObject(
        "Query",
        f'ВЫБРАТЬ ПЕРВЫЕ 1 Т.Ссылка, Т.Предмет ИЗ Задача.ЗадачаИсполнителя КАК Т ГДЕ Т.Номер = "{number}"',
    )
    .Execute()
    .Unload()
    .Get(0)
)
subj = row.Предмет
print("subject", subj.Метаданные().Имя, subj.Номер)

for cat in ("CRM_ИнтересПрисоединенныеФайлы", "CRM_БизнесПроцессПрисоединенныеФайлы"):
    q = f"""ВЫБРАТЬ ПЕРВЫЕ 10
        Ф.Наименование, Ф.Расширение, Ф.Размер, Ф.Описание
        ИЗ Справочник.{cat} КАК Ф
        ГДЕ Ф.ВладелецФайла = &Ref"""
    try:
        query = app.NewObject("Query", q)
        query.SetParameter("Ref", subj)
        t = query.Execute().Unload()
        print(f"\n{cat}: {t.Count()} files")
        for i in range(min(5, t.Count())):
            r = t.Get(i)
            print(
                " ",
                getattr(r, "Наименование", ""),
                getattr(r, "Расширение", ""),
                getattr(r, "Размер", ""),
            )
    except Exception as exc:
        print(cat, "FAIL", str(exc)[:200])
