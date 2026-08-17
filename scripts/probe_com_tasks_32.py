"""COM task query via 32-bit Python + V83 COMConnector/Application."""
from __future__ import annotations

import os
import struct
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

for k, v in env.items():
    if k.startswith(("ERP_", "ONEC_", "ODATA_")):
        os.environ.setdefault(k, v)

print("python_bitness:", struct.calcsize("P") * 8)
print("ERP_LOGIN:", env.get("ERP_LOGIN", ""))

conn_variants = [
    (
        "web",
        f'Srvr="http://{env.get("ONEC_COM_SERVER") or "192.168.2.229:81"}";'
        f'Ref="{env.get("ONEC_COM_REF") or "erp_pm"}";'
        f'Usr="{env.get("ERP_LOGIN")}";'
        f'Pwd="{env.get("ERP_PASSWORD")}";',
    ),
    (
        "tcp",
        f'Srvr="{env.get("ONEC_COM_SERVER") or "192.168.2.229:81"}";'
        f'Ref="{env.get("ONEC_COM_REF") or "erp_pm"}";'
        f'Usr="{env.get("ERP_LOGIN")}";'
        f'Pwd="{env.get("ERP_PASSWORD")}";',
    ),
    (
        "host_only",
        f'Srvr="192.168.2.229";Ref="erp_pm";Usr="{env.get("ERP_LOGIN")}";Pwd="{env.get("ERP_PASSWORD")}";',
    ),
]

QUERIES = {
    "open_all": """ВЫБРАТЬ ПЕРВЫЕ 20
    Задача.Наименование КАК Наименование,
    Задача.Дата КАК Дата,
    Задача.Выполнена КАК Выполнена,
    Задача.Исполнитель.Наименование КАК Исполнитель
    ИЗ Задача.ЗадачаИсполнителя КАК Задача
    ГДЕ НЕ Задача.Выполнена
    УПОРЯДОЧИТЬ ПО Дата УБЫВ""",
    "accepted_open": """ВЫБРАТЬ ПЕРВЫЕ 20
    Задача.Наименование КАК Наименование,
    Задача.Дата КАК Дата,
    Задача.Выполнена КАК Выполнена,
    Задача.Исполнитель.Наименование КАК Исполнитель
    ИЗ Задача.ЗадачаИсполнителя КАК Задача
    ГДЕ НЕ Задача.Выполнена
        И Задача.ПринятаКИсполнению
    УПОРЯДОЧИТЬ ПО Дата УБЫВ""",
    "my_open": """ВЫБРАТЬ ПЕРВЫЕ 20
    Задача.Наименование КАК Наименование,
    Задача.Дата КАК Дата,
    Задача.Выполнена КАК Выполнена,
    Задача.Исполнитель.Наименование КАК Исполнитель
    ИЗ Задача.ЗадачаИсполнителя КАК Задача
    ГДЕ НЕ Задача.Выполнена
        И Задача.Исполнитель = &ТекущийПользователь
    УПОРЯДОЧИТЬ ПО Дата УБЫВ""",
}


def query_tasks(app, label: str, query_text: str) -> int:
    try:
        query = app.NewObject("Query", query_text)
        if "&ТекущийПользователь" in query_text:
            query.SetParameter("ТекущийПользователь", app.CurrentUser())
        sel = query.Execute().Choose().Select()
        rows = []
        while sel.Next() and len(rows) < 20:
            rows.append(
                {
                    "date": str(getattr(sel, "Дата", "") or "")[:10],
                    "name": str(getattr(sel, "Наименование", "") or ""),
                    "executor": str(getattr(sel, "Исполнитель", "") or ""),
                }
            )
        print(f"\n=== COM [{label}]: {len(rows)} rows ===")
        for r in rows:
            print(f"  {r['date']} | {r['executor'][:25]:25} | {r['name'][:60]}")
        return len(rows)
    except Exception as exc:
        print(f"\n=== COM [{label}] FAIL:", exc)
        return -1


def main() -> int:
    import win32com.client

    connector = None
    for progid in ("V83.COMConnector.1", "V83.COMConnector"):
        try:
            connector = win32com.client.Dispatch(progid)
            print(f"Dispatch {progid} OK")
            break
        except Exception as exc:
            print(f"Dispatch {progid} FAIL:", exc)

    if connector is None:
        return 1

    for label, conn in conn_variants:
        print(f"\n--- Connect ({label}) ---")
        print("connection:", conn.replace(env.get("ERP_PASSWORD", ""), "***"))
        try:
            app = connector.Connect(conn)
            print("Connect OK")
            try:
                user = app.CurrentUser()
                print("CurrentUser:", str(user))
            except Exception as exc:
                print("CurrentUser FAIL:", exc)
            total = 0
            for qname, qtext in QUERIES.items():
                n = query_tasks(app, qname, qtext)
                if n > 0:
                    total = n
            return 0 if total >= 0 else 1
        except Exception as exc:
            print("Connect FAIL:", exc)

    print("\nCOM connect failed for all variants")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
