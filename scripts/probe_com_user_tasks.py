"""Find executor GUID for ERP user + list metadata task names via COM."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

BASE = env["ODATA_BASE_URL"].rstrip("/")
AUTH = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
FIO = env["ERP_LOGIN"]

# OData: search user in catalogs
for entity in (
    "Catalog_Пользователи",
    "Catalog_ПользователиOData",
    "InformationRegister_ИсполнителиЗадач",
):
    url = f"{BASE}/{entity}"
    r = httpx.get(url, params={"$format": "json", "$top": "3", "$filter": "contains(Description,'Жалыбин')"}, auth=AUTH, timeout=60)
    print(entity, r.status_code, r.text[:150].replace("\n", " "))

# COM metadata introspection
conn = f'Srvr="192.168.2.229";Ref="erp_pm";Usr="{FIO}";Pwd="{env["ERP_PASSWORD"]}";'
import win32com.client

connector = win32com.client.Dispatch("V83.COMConnector")
app = connector.Connect(conn)

for qname, q in [
    ("bp_open", """ВЫБРАТЬ ПЕРВЫЕ 10
        З.Наименование, З.Дата
        ИЗ БизнесПроцесс.Задание КАК З
        ГДЕ НЕ З.Завершен
        УПОРЯДОЧИТЬ ПО З.Дата УБЫВ"""),
    ("task_by_user", """ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Наименование, Т.Дата, Т.Выполнена
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель = &П
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""),
]:
    try:
        query = app.NewObject("Query", q)
        if "task_by_user" in qname:
            u = app.ПользователиИнформационнойБазы.ТекущийПользователь()
            query.SetParameter("П", u)
        sel = query.Execute().Choose().Select()
        n = 0
        print(f"\n=== {qname} ===")
        while sel.Next() and n < 15:
            print(" ", str(getattr(sel, "Дата", ""))[:10], str(getattr(sel, "Наименование", ""))[:70])
            n += 1
        print("rows", n)
    except Exception as exc:
        print(qname, "FAIL", exc)
