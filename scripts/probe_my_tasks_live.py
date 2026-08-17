"""Fetch open ERP tasks for current user (OData + client-side executor filter)."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip().strip('"').strip("'")

BASE = env["ODATA_BASE_URL"].rstrip("/")
USER = (env.get("ERP_LOGIN", ""), env.get("ERP_PASSWORD", ""))
FIO = env.get("ERP_LOGIN", "")
ENTITY = "Task_ЗадачаИсполнителя"


def main() -> int:
    params = {
        "$format": "json",
        "$top": "100",
        "$filter": "Executed eq false and ПринятаКИсполнению eq true",
    }
    r = httpx.get(f"{BASE}/{ENTITY}", params=params, auth=USER, timeout=90.0)
    print("auth:", FIO)
    print("status:", r.status_code)
    if r.status_code != 200:
        print(r.text[:300])
        return 1

    rows = r.json().get("value") or []
    print("open accepted tasks (all executors):", len(rows))

    # Try expand executor name if available
    params2 = dict(params)
    params2["$expand"] = "Исполнитель($select=Description)"
    r2 = httpx.get(f"{BASE}/{ENTITY}", params=params2, auth=USER, timeout=90.0)
    mine: list[dict] = []
    if r2.status_code == 200:
        for row in r2.json().get("value") or []:
            ex = row.get("Исполнитель") or {}
            name = (ex.get("Description") or ex.get("Ref_Key") or "") if isinstance(ex, dict) else str(ex)
            if FIO.lower() in str(name).lower() or name == FIO:
                mine.append(row)
        print("expanded executor filter:", len(mine), "for", FIO)
    else:
        print("expand failed:", r2.status_code, r2.text[:120])

    show = mine if mine else rows[:20]
    label = "YOUR tasks" if mine else "ALL open tasks (no executor name in OData)"
    print(f"\n=== {label}: {len(show)} ===")
    for t in show[:20]:
        num = t.get("Number", "")
        dt = str(t.get("Date", ""))[:10]
        desc = (t.get("Description") or "")[:70]
        ex = t.get("Исполнитель")
        exs = ex.get("Description", str(ex)[:8]) if isinstance(ex, dict) else str(ex)[:8]
        print(f"  {num} | {dt} | {exs:20} | {desc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
