#!/usr/bin/env python3
"""Find COM task numbers anywhere in OData (any Executed state)."""

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
AUTH = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
TARGET = {"00-Л-000036795", "00-Л-000036791", "36795", "36791"}


def main() -> None:
    entities = ["Task_ЗадачаИсполнителя", "BusinessProcess_Задание"]
    with httpx.Client() as client:
        for entity in entities:
            print(f"\n=== {entity} ===")
            found = []
            skip = 0
            while skip < 15000:
                r = client.get(
                    f"{BASE}/{entity}",
                    params={"$format": "json", "$top": "200", "$skip": str(skip), "$orderby": "Date desc"},
                    auth=AUTH,
                    timeout=90,
                )
                if r.status_code != 200:
                    print("HTTP", r.status_code, r.text[:120])
                    break
                rows = r.json().get("value") or []
                if not rows:
                    break
                for row in rows:
                    num = str(row.get("Number") or "")
                    if any(t in num for t in TARGET):
                        found.append(row)
                        isp = {k: row[k] for k in row if "сполн" in k.lower()}
                        print("HIT", num, "Executed/Completed", row.get("Executed", row.get("Completed")), isp)
                skip += len(rows)
            print(f"scanned {skip}, hits {len(found)}")


if __name__ == "__main__":
    main()
