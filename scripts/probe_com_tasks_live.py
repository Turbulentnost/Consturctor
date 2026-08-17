"""Try COM/COMConnector connect and list user tasks."""
from __future__ import annotations

import json
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

conn = f'Srvr="{env.get("ONEC_COM_SERVER") or "192.168.2.229:81"}";Ref="{env.get("ONEC_COM_REF") or "erp_pm"}";Usr="{env.get("ERP_LOGIN")}";Pwd="{env.get("ERP_PASSWORD")}";'
print("connection:", conn.replace(env.get("ERP_PASSWORD", ""), "***"))


def try_comconnector() -> None:
    print("\n=== V83.COMConnector (64-bit?) ===")
    import win32com.client

    for progid in ("V83.COMConnector", "V83c.COMConnector", "V83.Application", "V83c.Application"):
        try:
            obj = win32com.client.Dispatch(progid)
            print(progid, "Dispatch OK", type(obj))
            if hasattr(obj, "Connect"):
                app = obj.Connect(conn)
                print("  Connect OK", type(app))
                return app
        except Exception as exc:
            print(progid, "FAIL", exc)
    for progid in ("V83.Application", "V83c.Application"):
        try:
            obj = win32com.client.GetActiveObject(progid)
            print(progid, "GetActiveObject OK")
            return obj
        except Exception as exc:
            print(progid, "active FAIL", exc)
    return None


def query_tasks(app) -> None:
    print("\n=== Query tasks via COM ===")
    # Standard 1C query for performer tasks
    queries = [
        """ВЫБРАТЬ ПЕРВЫЕ 20
        Задача.Ссылка КАК Ссылка,
        Задача.Наименование КАК Наименование,
        Задача.Дата КАК Дата,
        Задача.Выполнена КАК Выполнена
        ИЗ Задача.ЗадачаИсполнителя КАК Задача
        ГДЕ НЕ Задача.Выполнена
        УПОРЯДОЧИТЬ ПО Дата УБЫВ""",
    ]
    for q in queries:
        try:
            query = app.NewObject("Query", q)
            result = query.Execute().Choose()
            sel = result.Select()
            rows = []
            while sel.Next() and len(rows) < 20:
                rows.append(
                    {
                        "name": str(getattr(sel, "Наименование", "") or ""),
                        "date": str(getattr(sel, "Дата", "") or ""),
                        "done": bool(getattr(sel, "Выполнена", False)),
                    }
                )
            print("rows", len(rows))
            for r in rows[:15]:
                print(" ", r.get("date", "")[:10], r.get("name", "")[:80])
            return
        except Exception as exc:
            print("query FAIL", exc)


def main() -> None:
    try:
        import win32com.client  # noqa: F401
    except ImportError:
        print("pywin32 not installed")
        return
    app = try_comconnector()
    if app is None:
        print("\nCOM unavailable — need 32-bit Python + running 1C or COMConnector")
        return
    query_tasks(app)


if __name__ == "__main__":
    main()
