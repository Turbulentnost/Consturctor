#!/usr/bin/env python3
"""Cross-check COM task numbers against OData Task_ЗадачаИсполнителя."""

from __future__ import annotations

import json
import sys
import urllib.request
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


def com_tasks() -> list[dict]:
    body = json.dumps({"payload": {"mine_only": True, "prefer_crm": False, "limit": 30}}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:7831/api/v1/tools/onec.com.query_tasks/invoke",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode())
    return (data.get("data") or {}).get("tasks") or []


def odata_by_number(client: httpx.Client, number: str, auth: tuple[str, str]) -> dict | None:
    flt = f"Number eq '{number}'"
    r = client.get(
        f"{BASE}/Task_ЗадачаИсполнителя",
        params={"$format": "json", "$top": "5", "$filter": flt},
        auth=auth,
        timeout=90,
    )
    print(f"  OData Number={number} auth={auth[0][:15]} -> {r.status_code}")
    if r.status_code != 200:
        print("   ", r.text[:200])
        return None
    rows = r.json().get("value") or []
    return rows[0] if rows else None


def main() -> None:
    print("COM tasks for", FIO)
    tasks = com_tasks()
    print("count:", len(tasks))
    for t in tasks:
        print(" ", t.get("number"), "|", str(t.get("description", ""))[:60])

    user_ref = "41290a43-5990-11f1-980e-6cb31113810e"
    with httpx.Client() as client:
        for auth in (USER, SVC):
            print(f"\n=== OData lookup auth={auth[0]} ===")
            for t in tasks:
                num = t.get("number", "")
                row = odata_by_number(client, num, auth)
                if not row:
                    print("    NOT FOUND in OData")
                    continue
                isp = row.get("Исполнитель") or row.get("Исполнитель_Key")
                isp_keys = {k: row[k] for k in row if "сполн" in k.lower()}
                print("    Executed:", row.get("Executed"))
                print("    Исполнитель fields:", isp_keys)
                print("    matches user_ref:", str(isp) == user_ref)


if __name__ == "__main__":
    main()
