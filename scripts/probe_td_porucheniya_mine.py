"""Query open «Поручения (ТД)» tabular rows for current user."""
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
safe_fio = fio.replace('"', '""')
md = app.Metadata

reg = md.InformationRegisters.ТД_ЗадачиПротоколов
print("Register ТД_ЗадачиПротоколов dims/resources:")
for i in range(reg.Dimensions.Count()):
    d = reg.Dimensions.Get(i)
    print(" dim", d.Name, getattr(d, "Synonym", ""))
for i in range(reg.Resources.Count()):
    r = reg.Resources.Get(i)
    print(" res", r.Name, getattr(r, "Synonym", ""))
for i in range(reg.Attributes.Count()):
    a = reg.Attributes.Get(i)
    print(" attr", a.Name, getattr(a, "Synonym", ""))

queries = {
    "td_tab_mine": f"""ВЫБРАТЬ ПЕРВЫЕ 50
        Д.Номер КАК DocNumber,
        Д.Дата КАК DocDate,
        Д.ОЧем КАК About,
        Д.Статус КАК DocStatus,
        Стр.Мероприятие КАК Title,
        Стр.СрокИсполнения КАК DueDate,
        Стр.ОтветственноеЛицо.Наименование КАК Performer,
        Стр.Приоритет КАК Priority
        ИЗ Документ.ТД_Поручения.Поручения КАК Стр
        ЛЕВОЕ СОЕДИНЕНИЕ Документ.ТД_Поручения КАК Д
            ПО Стр.Ссылка = Д.Ссылка
        ГДЕ НЕ Д.ПометкаУдаления
            И Стр.ОтветственноеЛицо.Наименование = "{safe_fio}"
        УПОРЯДОЧИТЬ ПО Стр.СрокИсполнения УБЫВ, Д.Дата УБЫВ""",
    "td_tab_open_due": f"""ВЫБРАТЬ ПЕРВЫЕ 50
        Д.Номер, Д.Дата, Стр.Мероприятие, Стр.СрокИсполнения,
        Стр.ОтветственноеЛицо.Наименование, Стр.Приоритет
        ИЗ Документ.ТД_Поручения.Поручения КАК Стр
        ЛЕВОЕ СОЕДИНЕНИЕ Документ.ТД_Поручения КАК Д
            ПО Стр.Ссылка = Д.Ссылка
        ГДЕ НЕ Д.ПометкаУдаления
            И Стр.ОтветственноеЛицо.Наименование = "{safe_fio}"
            И Стр.СрокИсполнения > ДАТАВРЕМЯ(2001, 1, 1)
        УПОРЯДОЧИТЬ ПО Стр.СрокИсполнения""",
    "register_mine_open": f"""ВЫБРАТЬ ПЕРВЫЕ 30
        Р.НомерПунктаПротокола, Р.Задача, Р.СрокИсполнения, Р.ДатаПостановкиЗадачи,
        Р.Ответственный.Наименование, Р.Автор.Наименование,
        Р.Выполнена, Р.Отправлена, Р.ТемаСовещания.Наименование
        ИЗ РегистрСведений.ТД_ЗадачиПротоколов КАК Р
        ГДЕ НЕ Р.Выполнена
            И Р.Ответственный.Наименование = "{safe_fio}"
        УПОРЯДОЧИТЬ ПО Р.СрокИсполнения""",
}

for name, q in queries.items():
    print(f"\n--- {name} ---")
    try:
        table = app.NewObject("Query", q).Execute().Unload()
        print("rows:", table.Count())
        if table.Count() and hasattr(table, "Columns"):
            print("cols:", [table.Columns.Get(i).Name for i in range(table.Columns.Count())])
        for i in range(min(15, table.Count())):
            row = table.Get(i)
            parts = []
            for ci in range(table.Columns.Count()):
                cn = table.Columns.Get(ci).Name
                v = getattr(row, cn, "")
                if v not in (None, ""):
                    parts.append(f"{cn}={str(v)[:60]}")
            print(" ", " | ".join(parts))
    except Exception as exc:
        print("FAIL:", str(exc)[:350])
