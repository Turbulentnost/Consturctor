#!/usr/bin/env python3
"""Inspect OData Task_ЗадачаИсполнителя executor field + filter behavior."""

from __future__ import annotations

import json
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
USER = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
SVC = (env["ODATA_USERNAME"], env["ODATA_PASSWORD"])
FIO = env["ERP_LOGIN"]
USER_REF = "41290a43-5990-11f1-980e-6cb31113810e"


def sample(auth_name: str, auth: tuple[str, str]) -> None:
    print(f"\n=== {auth_name} ===")
    params = {
        "$format": "json",
        "$top": "5",
        "$expand": "Исполнитель($select=Description,Ref_Key)",
        "$orderby": "Date desc",
    }
    r = httpx.get(f"{BASE}/Task_ЗадачаИсполнителя", params=params, auth=auth, timeout=60)
    print("sample status:", r.status_code)
    if r.status_code != 200:
        print(r.text[:200])
        return
    for row in r.json().get("value") or []:
        ex = row.get("Исполнитель")
        isp_keys = [k for k in row if "сполн" in k.lower() or "Executor" in k]
        print(
            " ",
            row.get("Number"),
            "Executed=",
            row.get("Executed"),
            "Исполнитель=",
            ex,
            "extra=",
            {k: row[k] for k in isp_keys},
        )

    flt = f"Executed eq false and Исполнитель eq guid'{USER_REF}'"
    r2 = httpx.get(
        f"{BASE}/Task_ЗадачаИсполнителя",
        params={"$format": "json", "$top": "5", "$filter": flt},
        auth=auth,
        timeout=60,
    )
    print("filter status:", r2.status_code, "rows:", len(r2.json().get("value") or []) if r2.status_code == 200 else 0)
    if r2.status_code == 200:
        for row in r2.json().get("value") or []:
            print("  filtered:", row.get("Number"), row.get("Исполнитель"), row.get("Executed"))

    # scan open tasks matching FIO via expand (slow but accurate)
    mine = []
    for skip in range(0, 500, 100):
        p = {
            "$format": "json",
            "$top": "100",
            "$skip": str(skip),
            "$filter": "Executed eq false",
            "$expand": "Исполнитель($select=Description,Ref_Key)",
        }
        rr = httpx.get(f"{BASE}/Task_ЗадачаИсполнителя", params=p, auth=auth, timeout=60)
        if rr.status_code != 200:
            break
        rows = rr.json().get("value") or []
        if not rows:
            break
        for row in rows:
            ex = row.get("Исполнитель") or {}
            name = ex.get("Description", "") if isinstance(ex, dict) else str(ex)
            ref = ex.get("Ref_Key", "") if isinstance(ex, dict) else ""
            if FIO in name or ref == USER_REF:
                mine.append(row)
    print(f"open tasks for {FIO} via expand scan (500 max): {len(mine)}")
    for row in mine[:5]:
        ex = row.get("Исполнитель") or {}
        print("  MINE:", row.get("Number"), ex.get("Description"), (row.get("Description") or "")[:50])


def main() -> None:
    sample("ERP", USER)
    sample("SVC", SVC)


if __name__ == "__main__":
    main()
