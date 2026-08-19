#!/usr/bin/env python3
"""Lookup known COM task numbers in OData."""

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
USER = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
SVC = (env["ODATA_USERNAME"], env["ODATA_PASSWORD"])
NUMBERS = ["00-Л-000036795", "00-Л-000036791"]
USER_REF = "41290a43-5990-11f1-980e-6cb31113810e"


def main() -> None:
    with httpx.Client() as client:
        for auth_name, auth in [("ERP", USER), ("SVC", SVC)]:
            print(f"\n=== {auth_name} ===")
            for num in NUMBERS:
                r = client.get(
                    f"{BASE}/Task_ЗадачаИсполнителя",
                    params={"$format": "json", "$top": "5", "$filter": f"Number eq '{num}'"},
                    auth=auth,
                    timeout=90,
                )
                print(f"{num}: HTTP {r.status_code}")
                if r.status_code != 200:
                    print(r.text[:200])
                    continue
                rows = r.json().get("value") or []
                if not rows:
                    print("  not found")
                    continue
                row = rows[0]
                isp_keys = {k: row[k] for k in row if "сполн" in k.lower()}
                print("  Executed:", row.get("Executed"))
                print("  Description:", (row.get("Description") or "")[:60])
                print("  executor fields:", isp_keys)
                print("  user_ref match:", any(str(v) == USER_REF for v in isp_keys.values()))


if __name__ == "__main__":
    main()
