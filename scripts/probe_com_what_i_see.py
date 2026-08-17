"""Show what COM session sees at 1C login: modules, start page, task widgets."""
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

print("=" * 60)
print("1. ЖИВОЙ КЛИЕНТ 1С (если открыт у вас на экране)")
print("=" * 60)
live_app = None
for progid in ("V83.Application", "V83c.Application", "V83.Application.1"):
    try:
        live_app = win32com.client.GetActiveObject(progid)
        print(f"OK GetActiveObject({progid}) — вижу ваш открытый 1С")
        try:
            u = live_app.ПользователиИнформационнойБазы.ТекущийПользователь()
            print("  GUI пользователь:", getattr(u, "ПолноеИмя", u))
        except Exception as exc:
            print("  user FAIL:", exc)
        break
    except Exception:
        print(f"  {progid}: не зарегистрирован / клиент не открыт")

print("\n" + "=" * 60)
print("2. COM-СЕССИЯ (как platform-tool-onec-com)")
print("=" * 60)
conn = (
    f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";'
    f'Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
)
app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
uib = app.ПользователиИнформационнойБазы
user = uib.ТекущийПользователь()
fio = str(getattr(user, "ПолноеИмя", "") or env["ERP_LOGIN"])
print("Пользователь:", fio)
print("Имя IB:", getattr(user, "Имя", ""))

# Roles
print("\n--- Роли пользователя ---")
try:
    roles = uib.РолиПользователя(user)
    if hasattr(roles, "Count"):
        for i in range(roles.Count()):
            print(" ", roles.Get(i))
    else:
        print(" ", roles)
except Exception as exc:
    print(" FAIL:", exc)

md = app.Metadata

print("\n--- Подсистемы CRM / старт / задачи ---")
subs = md.Subsystems
for i in range(subs.Count()):
    name = subs.Get(i).Name
    if any(x in name for x in ("CRM", "Старт", "Начал", "Задач", "Документооборот", "Главн")):
        syn = ""
        try:
            syn = subs.Get(i).Synonym
        except Exception:
            pass
        print(f"  {name}" + (f" ({syn})" if syn else ""))

print("\n--- Обработки «главная / мои дела / задачи» ---")
for i in range(md.DataProcessors.Count()):
    name = md.DataProcessors.Get(i).Name
    if any(x in name for x in ("МоиДела", "МоиЗадач", "Стартов", "Начальн", "РабочийСтол", "CRM_АРМ")):
        print(" ", name)

print("\n--- Общие формы стартовой / задач ---")
for i in range(md.CommonForms.Count()):
    name = md.CommonForms.Get(i).Name
    if any(x in name for x in ("Старт", "Начал", "МоиЗадач", "Задач", "РабочийСтол", "CRM")):
        print(" ", name)

print("\n" + "=" * 60)
print("3. API «как на главной» — БизнесПроцессыИЗадачи / CRM")
print("=" * 60)

api_targets = [
    ("БизнесПроцессыИЗадачи", "ПолучитьЗадачиПользователя", [user]),
    ("БизнесПроцессыИЗадачи", "ПолучитьЗадачиПользователя", [user, False]),
    ("CRM_БизнесПроцессыИЗадачиСервер", "ПолучитьЗадачиПользователя", [user]),
    ("CRM_БизнесПроцессыИЗадачиСервер", "ЗадачиПользователя", [user]),
]

for mgr_name, method, args in api_targets:
    print(f"\n--- {mgr_name}.{method} ---")
    try:
        mgr = getattr(app, mgr_name)
        result = getattr(mgr, method)(*args)
        if hasattr(result, "Count"):
            print("Count:", result.Count())
            for j in range(min(15, result.Count())):
                item = result.Get(j) if hasattr(result, "Get") else result[j]
                num = str(getattr(item, "Номер", getattr(item, "Number", "")))[:20]
                desc = str(getattr(item, "Наименование", getattr(item, "Description", item)))[:65]
                print(f"  {num} | {desc}")
        elif hasattr(result, "Unload"):
            t = result.Unload()
            print("rows:", t.Count())
            for j in range(min(15, t.Count())):
                row = t.Get(j)
                print(f"  {getattr(row, 'Номер', '')} | {str(getattr(row, 'Наименование', ''))[:65]}")
        else:
            print("result:", str(result)[:300])
    except Exception as exc:
        print("FAIL:", str(exc)[:200])

print("\n" + "=" * 60)
print("4. CRM_АРМ_МоиДела (обработка «Мои дела»)")
print("=" * 60)
try:
    proc_meta = md.DataProcessors.CRM_АРМ_МоиДела
    print("Metadata:", proc_meta.Name, "|", getattr(proc_meta, "Synonym", ""))
    proc_mgr = app.DataProcessors.CRM_АРМ_МоиДела
    inst = proc_mgr.Create()
    print("Create OK:", type(inst))
    interesting = [m for m in dir(inst) if not m.startswith("_") and any(
        x in m.lower() for x in ("задач", "task", "дел", "спис", "получ", "сформ", "заполн")
    )]
    print("Methods:", interesting[:25])
    for method in ("Заполнить", "Сформировать", "ПолучитьЗадачи", "Обновить", "Выполнить"):
        if method in dir(inst):
            try:
                r = getattr(inst, method)()
                print(f"  {method}() ->", type(r), str(r)[:150])
            except Exception as exc:
                print(f"  {method}() FAIL:", str(exc)[:120])
except Exception as exc:
    print("FAIL:", exc)

print("\n" + "=" * 60)
print("5. Сводка списков задач (для сравнения с вашим экраном)")
print("=" * 60)

lists = {
    "CRM_ЗадачиПользователей (открытые)": f"""ВЫБРАТЬ
        Р.Номер, Р.Наименование, Р.Поставлено
        ИЗ РегистрСведений.CRM_ЗадачиПользователей КАК Р
        ГДЕ Р.Пользователь.Наименование = "{fio.replace('"', '""')}"
            И Р.Закрыта = ДАТАВРЕМЯ(1, 1, 1)
        УПОРЯДОЧИТЬ ПО Р.Поставлено УБЫВ""",
    "ЗадачаИсполнителя (не выполнена, мне)": f"""ВЫБРАТЬ
        Т.Номер, Т.Наименование, Т.Дата, Т.ПринятаКИсполнению
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И Т.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "ЗадачаИсполнителя (НЕ принята — «новые мне»)": f"""ВЫБРАТЬ
        Т.Номер, Т.Наименование, Т.Дата
        ИЗ Задача.ЗадачаИсполнителя КАК Т
        ГДЕ НЕ Т.Выполнена
            И НЕ Т.ПринятаКИсполнению
            И Т.Исполнитель.Наименование = "{fio.replace('"', '""')}"
        УПОРЯДОЧИТЬ ПО Т.Дата УБЫВ""",
    "BusinessProcess_Задание (активные)": """ВЫБРАТЬ ПЕРВЫЕ 20
        Б.Номер, Б.Наименование, Б.Дата, Б.Стартован, Б.Завершен
        ИЗ БизнесПроцесс.Задание КАК Б
        ГДЕ Б.Стартован И НЕ Б.Завершен
        УПОРЯДОЧИТЬ ПО Б.Дата УБЫВ""",
}

for title, q in lists.items():
    print(f"\n[{title}]")
    try:
        t = app.NewObject("Query", q).Execute().Unload()
        print(f"  строк: {t.Count()}")
        for j in range(min(10, t.Count())):
            row = t.Get(j)
            num = str(getattr(row, "Номер", "") or "")
            name = str(getattr(row, "Наименование", "") or "")[:60]
            extra = ""
            if hasattr(row, "ПринятаКИсполнению"):
                extra = f" | принята={getattr(row, 'ПринятаКИсполнению', '')}"
            print(f"    {num:16} | {name}{extra}")
    except Exception as exc:
        print("  FAIL:", str(exc)[:180])

print("\n" + "=" * 60)
print("ГОТОВО. Сравните списки выше с тем, что видите на экране 1С.")
print("Напишите: какой раздел открыт (CRM / ERP / ДО) и номера задач с экрана.")
print("=" * 60)
