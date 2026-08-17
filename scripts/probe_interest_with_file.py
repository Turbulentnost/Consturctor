"""Resolve task by CRM interest with attachment."""
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

interest = "И00-0001159"
q_tasks = f"""ВЫБРАТЬ ПЕРВЫЕ 5
    Т.Номер, Т.Наименование, Т.Дата, Т.СрокИсполнения, Т.Исполнитель.Наименование,
    Т.Автор.Наименование, Т.Выполнена, Т.Ссылка
    ИЗ Задача.ЗадачаИсполнителя КАК Т
    ГДЕ Т.Предмет.Номер = "{interest}"
    УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ"""
t = app.NewObject("Query", q_tasks).Execute().Unload()
print("tasks for interest", interest, ":", t.Count())
for i in range(t.Count()):
    r = t.Get(i)
    print(
        getattr(r, "Номер", ""),
        "|",
        str(getattr(r, "Наименование", ""))[:70],
        "|",
        getattr(r, "Дата", ""),
    )

q_files = f"""ВЫБРАТЬ
    Ф.Наименование, Ф.Расширение, Ф.Размер, Ф.Описание, Ф.ДатаСоздания,
    Ф.ТипХраненияФайла, Ф.ПутьКФайлу
    ИЗ Справочник.CRM_ИнтересПрисоединенныеФайлы КАК Ф
    ГДЕ Ф.ВладелецФайла.Номер = "{interest}\""""
tf = app.NewObject("Query", q_files).Execute().Unload()
print("\nfiles:", tf.Count())
for i in range(tf.Count()):
    r = tf.Get(i)
    print(" name:", getattr(r, "Наименование", ""))
    print(" ext:", getattr(r, "Расширение", ""))
    print(" size:", getattr(r, "Размер", ""))
    print(" desc:", str(getattr(r, "Описание", ""))[:200])
    print(" created:", getattr(r, "ДатаСоздания", ""))
    print(" storage:", getattr(r, "ТипХраненияФайла", ""))
    print(" path:", getattr(r, "ПутьКФайлу", ""))

# interest object fields
q_int = f"""ВЫБРАТЬ ПЕРВЫЕ 1
    И.Номер, И.Наименование, И.Дата, И.Описание, И.Комментарий,
    И.Ответственный.Наименование, И.Партнер.Наименование
    ИЗ Справочник.CRM_Интерес КАК И
    ГДЕ И.Номер = "{interest}\""""
try:
    ti = app.NewObject("Query", q_int).Execute().Unload()
    if ti.Count():
        r = ti.Get(0)
        for f in ("Номер", "Наименование", "Дата", "Описание", "Комментарий", "Ответственный", "Партнер"):
            print(f, ":", str(getattr(r, f, ""))[:300])
except Exception as exc:
    print("interest query fail:", exc)
