#!/usr/bin/env python3
"""Probe OData Document_ТД_Поручения (ACT00-*)."""
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
    key, _, value = line.partition("=")
    env[key.strip()] = value.strip().strip('"').strip("'")

base = env.get("ODATA_BASE_URL", "").rstrip("/")
auth = (
    env.get("ERP_LOGIN") or env.get("ODATA_USERNAME") or "",
    env.get("ERP_PASSWORD") or env.get("ODATA_PASSWORD") or "",
)
print("base:", base)

entity = "Document_ТД_Поручения"
queries = [
    f"{entity}?$format=json&$top=5&$orderby=Date desc",
    f"{entity}?$format=json&$top=5&$filter=startswith(Number,'ACT')",
    f"{entity}?$format=json&$top=1&$filter=Number eq 'ACT00-00088'",
    f"{entity}?$format=json&$top=5&$filter=startswith(Number,'АСТ')",
    f"{entity}?$format=json&$top=3&$expand=КтоДоложитОЗавершенииМероприятий,СекретарьРК&$orderby=Date desc",
]

with httpx.Client(auth=auth, timeout=90.0) as client:
    meta = client.get(f"{base}/$metadata")
    print("metadata:", meta.status_code, len(meta.content))
    if "ТД_Поруч" in meta.text:
        print("metadata contains ТД_Поруч")

    for path in queries:
        url = f"{base}/{path}"
        response = client.get(url)
        print("\n---", path[:80], "---")
        print("status:", response.status_code, "bytes:", len(response.content))
        if response.status_code != 200:
            print(response.text[:400])
            continue
        data = response.json()
        rows = list(data.get("value") or [])
        print("rows:", len(rows))
        if rows:
            print("keys sample:", sorted(rows[0].keys())[:40])
            for row in rows[:3]:
                who = row.get("КтоДоложитОЗавершенииМероприятий") or {}
                sec = row.get("СекретарьРК") or {}
                print(
                    "row:",
                    row.get("Number"),
                    "|",
                    str(row.get("ОЧем") or "")[:50],
                    "| who:",
                    who.get("Description") if isinstance(who, dict) else who,
                    "| sec:",
                    sec.get("Description") if isinstance(sec, dict) else sec,
                )
            if len(rows) == 1:
                print(json.dumps(rows[0], ensure_ascii=False, indent=2)[:2500])
