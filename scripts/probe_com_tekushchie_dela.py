"""Call ТекущиеДелаСервер / БизнесПроцессыИЗадачиСервер for home-page tasks."""
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

conn = f'Srvr="{env["ONEC_COM_SERVER"]}";Ref="{env["ONEC_COM_REF"]}";Usr="{env["ERP_LOGIN"]}";Pwd="{env["ERP_PASSWORD"]}";'
import win32com.client

app = win32com.client.Dispatch("V83.COMConnector").Connect(conn)
user = app.ПользователиИнформационнойБазы.ТекущийПользователь()
print("user:", user.ПолноеИмя)

modules = {
    "ТекущиеДелаСервер": [
        "ТекущиеДела",
        "ПолучитьТекущиеДела",
        "СформироватьСписокТекущихДел",
        "СформироватьТекущиеДела",
        "ДелаПользователя",
        "ЗадачиТекущиеДела",
        "КоличествоДел",
    ],
    "БизнесПроцессыИЗадачиСервер": [
        "ЗадачиПользователя",
        "ПолучитьЗадачиПользователя",
        "ВыбратьЗадачиПользователя",
        "СформироватьСписокЗадач",
        "КоличествоЗадачПользователя",
    ],
    "БизнесПроцессыИЗадачиВызовСервера": [
        "ЗадачиПользователя",
        "ПолучитьЗадачиПользователя",
        "СписокЗадач",
    ],
    "ИнтеграцияС1СДокументооборотВызовСервера": [
        "ПолучитьЗадачи",
        "ПолучитьЗадачиПользователя",
        "ПолучитьКоличествоЗадач",
        "ЕстьЗадачи",
    ],
}


def dump_result(label: str, result) -> None:
    print(f"  -> {label} type={type(result)}")
    if result is None:
        return
    if hasattr(result, "Unload"):
        t = result.Unload()
        print(f"     Unload rows={t.Count()} cols={t.Columns.Count() if hasattr(t, 'Columns') else '?'}")
        for i in range(min(20, t.Count())):
            row = t.Get(i)
            parts = []
            if hasattr(t, "Columns"):
                for c in range(min(6, t.Columns.Count())):
                    col = t.Columns.Get(c).Name
                    parts.append(f"{col}={str(getattr(row, col, ''))[:40]}")
            else:
                parts.append(str(row)[:120])
            print("    ", " | ".join(parts))
        return
    if hasattr(result, "Count"):
        try:
            cnt = result.Count()
            print(f"     Count={cnt}")
            for i in range(min(20, cnt)):
                item = result.Get(i) if hasattr(result, "Get") else None
                if item is not None:
                    name = str(getattr(item, "Наименование", getattr(item, "Description", item)))[:70]
                    num = str(getattr(item, "Номер", getattr(item, "Number", "")))[:20]
                    print(f"      {num} | {name}")
            return
        except Exception as exc:
            print("     Count fail", exc)
    print(f"     value={str(result)[:200]}")


for mod_name, methods in modules.items():
    print(f"\n======== {mod_name} ========")
    try:
        mod = getattr(app, mod_name)
    except Exception as exc:
        print("module missing", exc)
        continue
    for method in methods:
        try:
            fn = getattr(mod, method)
        except Exception:
            continue
        print(f"\n-- {method}()")
        tried = False
        for args in ([], [user], [user, False], [user, True], [False], [True]):
            try:
                dump_result(f"args={args}", fn(*args))
                tried = True
                break
            except Exception as exc:
                err = str(exc)
                if "Недостаточно" in err or "parameter" in err.lower() or "параметр" in err.lower():
                    continue
                print(f"  args={args} FAIL {err[:140]}")
                tried = True
                break
        if not tried:
            print("  no working signature")
