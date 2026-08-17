"""Find and query «Задачи Мне» in 1C ERP via COM."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip().strip('"').strip("'")

import win32com.client

conn = (
    f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";'
    f'Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
)
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
fio = str(getattr(user, "ПолноеИмя", "") or env["ERP_LOGIN"])
print("=== Пользователь ===")
print(fio)

md = app.Metadata
print("\n=== Метаданные: *Задач* + *Мне* ===")
for coll_name in (
    "Reports", "DataProcessors", "CommonForms", "CommonModules",
    "InformationRegisters", "Catalogs", "Documents", "Tasks",
):
    coll = getattr(md, coll_name, None)
    if coll is None:
        continue
    hits = []
    for i in range(coll.Count()):
        name = coll.Get(i).Name
        if ("Задач" in name and "Мне" in name) or name in ("ЗадачиМне", "CRM_ЗадачиПользователей"):
            hits.append(name)
    if hits:
        print(f"  {coll_name}: {hits}")

queries = {
    "crm_мои_задачи": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Р.Номер, Р.Наименование, Р.Поставлено, Р.КрайнийСрок
        ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
        ГДЕ Р.Пользователь.Наименование = "{fio.replace('"', '""')}"
            И Р.Закрыта = ДАТАВРЕМЯ(1, 1, 1)
        УПОРЯДОЧИТЬ ПО Р.Поставлено УБЫВ""",
    "erp_задача_исполнителя": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "задачи_мне_адресация": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Автор.Наименование <> Т.Исполнитель.Наименование
            И Т.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
}

print("\n=== Запросы «задачи мне» ===")
for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        table = app.NewObject("Query", q).Execute().Unload()
        print("найдено:", table.Count())
        for i in range(min(10, table.Count())):
            row = table.Get(i)
            num = str(getattr(row, "Номер", "") or "")
            title = str(getattr(row, "Наименование", "") or "")[:70]
            dt = str(getattr(row, "Дата", "") or getattr(row, "Поставлено", "") or "")[:16]
            print(f"  {num:16} | {dt} | {title}")
    except Exception as exc:
        print("FAIL", str(exc)[:200])

print("\n=== onec.com.query_tasks (:7831) ===")
body = json.dumps(
    {"payload": {"mine_only": True, "prefer_crm": True, "limit": 20}},
    ensure_ascii=False,
).encode("utf-8")
req = urllib.request.Request(
    "http://127.0.0.1:7831/api/v1/tools/onec.com.query_tasks/invoke",
    data=body,
    headers={"Content-Type": "application/json; charset=utf-8"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    if data.get("ok"):
        d = data.get("data") or {}
        print("source:", d.get("task_source"), "count:", d.get("count"))
        for t in d.get("tasks") or []:
            print(f"  {t.get('number',''):16} | {str(t.get('date',''))[:16]} | {str(t.get('description',''))[:70]}")
    else:
        print("FAIL", data.get("error"))
except Exception as exc:
    print("HTTP FAIL", exc)
