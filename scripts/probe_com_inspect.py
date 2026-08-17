"""Inspect 1C COM connection object."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

conn = (
    f'Srvr="192.168.2.229";Ref="erp_pm";'
    f'Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
)

import win32com.client

connector = win32com.client.Dispatch("V83.COMConnector")
app = connector.Connect(conn)
print("type:", type(app))
print("repr:", app)

for name in (
    "NewObject",
    "EvalExpr",
    "String",
    "Connect",
    "Metadata",
    "ПользователиИнформационнойБазы",
):
    print(name, hasattr(app, name))

queries = [
    ("count", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК C ИЗ Задача.ЗадачаИсполнителя"),
    ("count_open", "ВЫБРАТЬ КОЛИЧЕСТВО(*) КАК C ИЗ Задача.ЗадачаИсполнителя КАК З ГДЕ НЕ З.Выполнена"),
    ("users", "ВЫБРАТЬ ПЕРВЫЕ 5 Ссылка.Наименование КАК Наименование ИЗ Справочник.Пользователи КАК Ссылка"),
    ("my_name", f'ВЫБРАТЬ Наименование ИЗ Справочник.Пользователи ГДЕ Наименование ПОДОБНО "%Жалыбин%"'),
]
for label, q in queries:
    try:
        query = app.NewObject("Query", q)
        sel = query.Execute().Choose().Select()
        vals = []
        while sel.Next() and len(vals) < 5:
            vals.append(str(getattr(sel, "C", getattr(sel, "Наименование", ""))))
        print(label, "OK", vals if vals else "empty")
    except Exception as exc:
        print(label, "FAIL", exc)

try:
    md = app.Metadata()
    tasks = []
    for i in range(md.Tasks.Count()):
        tasks.append(md.Tasks.Get(i).Name)
    print("metadata tasks sample:", tasks[:10], "count", md.Tasks.Count())
except Exception as exc:
    print("metadata FAIL", exc)

try:
    uib = app.ПользователиИнформационнойБазы
    cur = uib.ТекущийПользователь()
    print("current user:", str(cur), getattr(cur, "Имя", ""), getattr(cur, "ПолноеИмя", ""))
except Exception as exc:
    print("current user FAIL", exc)
