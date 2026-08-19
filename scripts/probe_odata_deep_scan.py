#!/usr/bin/env python3
"""Deep scan OData open tasks for user ref or known numbers."""

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
USER_REF = "41290a43-5990-11f1-980e-6cb31113810e"
TARGET_NUMBERS = {"00-Л-000036795", "00-Л-000036791"}


def main() -> None:
    mine = []
    found_nums = set()
    skip = 0
    page = 200
    with httpx.Client() as client:
        while skip < 20000:
            r = client.get(
                f"{BASE}/Task_ЗадачаИсполнителя",
                params={
                    "$format": "json",
                    "$top": str(page),
                    "$skip": str(skip),
                    "$filter": "Executed eq false",
                    "$orderby": "Date desc",
                },
                auth=AUTH,
                timeout=90,
            )
            if r.status_code != 200:
                print("stop at skip", skip, "HTTP", r.status_code, r.text[:120])
                break
            rows = r.json().get("value") or []
            if not rows:
                print("end at skip", skip)
                break
            for row in rows:
                num = row.get("Number", "")
                if num in TARGET_NUMBERS:
                    found_nums.add(num)
                    isp = {k: row[k] for k in row if "сполн" in k.lower()}
                    print("FOUND", num, "Executed", row.get("Executed"), isp)
                ref = str(row.get("Исполнитель") or row.get("Исполнитель_Key") or "")
                if ref == USER_REF:
                    mine.append(row)
            skip += len(rows)
            if skip % 2000 == 0:
                print(f"scanned {skip}, mine={len(mine)}, found_nums={found_nums}")

    print(f"\nTOTAL scanned={skip}, mine={len(mine)}, found target numbers={found_nums}")
    for row in mine[:10]:
        print(" MINE:", row.get("Number"), (row.get("Description") or "")[:50])


if __name__ == "__main__":
    main()
