"""Find «Поручения (ТД)» metadata and open assignments for current user."""
from __future__ import annotations

import sys
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
fio = env["ERP_LOGIN"]
md = app.Metadata
safe_fio = fio.replace('"', '""')

print("=== Метаданные: *Поруч* / *ТД* ===")
for coll_name in ("Documents", "Catalogs", "InformationRegisters", "Reports", "DataProcessors"):
    coll = getattr(md, coll_name, None)
    if coll is None:
        continue
    hits = []
    for i in range(coll.Count()):
        obj = coll.Get(i)
        name = obj.Name
        syn = str(getattr(obj, "Synonym", "") or "")
        blob = f"{name} {syn}".casefold()
        if "поруч" in blob or ("тд" in blob and "задач" in blob):
            hits.append(f"{name} — {syn}")
    if hits:
        print(f"\n{coll_name} ({len(hits)}):")
        for h in hits[:30]:
            print(" ", h)

queries = {
    "doc_td_porucheniya": """ВЫБРАТЬ ПЕРВЫЕ 20
        Д.Номер, Д.Дата, Д.Комментарий, Д.Ответственный.Наименование,
        Д.СрокИсполнения, Д.Проведен, Д.ПометкаУдаления
        ИЗ Документ.ТД_Поручения КАК Д
        ГДЕ НЕ Д.ПометкаУдаления
        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ""",
    "doc_td_poruchenie": """ВЫБРАТЬ ПЕРВЫЕ 20
        Д.Номер, Д.Дата, Д.Комментарий, Д.Ответственный.Наименование
        ИЗ Документ.ТД_Поручение КАК Д
        ГДЕ НЕ Д.ПометкаУдаления
        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ""",
    "doc_poruchenie_td": """ВЫБРАТЬ ПЕРВЫЕ 20
        Д.Номер, Д.Дата, Д.Комментарий
        ИЗ Документ.ПоручениеТД КАК Д
        ГДЕ НЕ Д.ПометкаУдаления
        УПОРЯДОЧИТЬ ПО Д.Дата УБЫВ""",
    "tasks_with_poruchen_title": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения,
        Т.Исполнитель.Наименование, Т.Автор.Наименование, Т.Предмет
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = "{safe_fio}"
            И (Т.Наименование ПОДОБНО "%Исполнить задачу%"
                ИЛИ Т.Наименование ПОДОБНО "%поручен%"
                ИЛИ Т.Наименование ПОДОБНО "%протокол%")
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "bp_zadanie_mine": f"""ВЫБРАТЬ ПЕРВЫЕ 20
        Б.Номер, Б.Наименование, Б.Дата, Б.СрокИсполнения,
        Б.Исполнитель.Наименование, Б.Автор.Наименование
        ИЗ БизнесПроцесс.Задание КАК Б
        ГДЕ Б.Стартован И НЕ Б.Завершен
            И Б.Исполнитель.Наименование = "{safe_fio}"
        УПОРЯДОЧИТЬ ПО Б.Дата УБЫВ""",
}

print("\n=== Запросы поручений ===")
for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        table = app.NewObject("Query", q).Execute().Unload()
        print("rows:", table.Count())
        for i in range(min(10, table.Count())):
            row = table.Get(i)
            parts = []
            for col in ("Number", "Номер", "Description", "Наименование", "Date", "Дата",
                        "DueDate", "СрокИсполнения", "Executor", "Исполнитель", "Author", "Автор", "Comment", "Комментарий"):
                v = getattr(row, col, None)
                if v not in (None, ""):
                    parts.append(f"{col}={str(v)[:55]}")
            print(" ", " | ".join(parts) if parts else row)
    except Exception as exc:
        print("FAIL:", str(exc)[:220])
