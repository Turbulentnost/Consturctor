#!/usr/bin/env python3
"""Probe OData: исполнители и задачи в Document_ТД_Поручения и связанных регистрах."""
from __future__ import annotations

import json
import re
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

base = env["ODATA_BASE_URL"].rstrip("/")
auth = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
entity = "Document_ТД_Поручения"

with httpx.Client(auth=auth, timeout=120.0) as client:
    # one ACT doc with lines
    path = (
        f"{entity}?$format=json&$top=1"
        f"&$filter=startswith(Number,'АСТ')"
        f"&$expand=КтоДоложитОЗавершенииМероприятий"
        f"&$orderby=Date desc"
    )
    r = client.get(f"{base}/{path}")
    print("doc status", r.status_code)
    row = (r.json().get("value") or [{}])[0]
    print("number:", row.get("Number"), "about:", str(row.get("ОЧем") or "")[:60])
    lines = row.get("Поручения") or []
    print("Поручения lines:", len(lines))
    if lines:
        print("line keys:", sorted(lines[0].keys()))
        print(json.dumps(lines[:5], ensure_ascii=False, indent=2)[:5000])

    # docs with most lines
    path2 = f"{entity}?$format=json&$top=10&$filter=startswith(Number,'АСТ')&$orderby=Date desc"
    r2 = client.get(f"{base}/{path2}")
    for doc in r2.json().get("value") or []:
        n = len(doc.get("Поручения") or [])
        if n:
            print(f"  {doc.get('Number')}: {n} lines")

    meta = client.get(f"{base}/$metadata").text
    for needle in (
        "InformationRegister_ТД_Задачи",
        "Task_ЗадачаИсполнителя",
        "Catalog_Пользователи",
        "Исполнител",
    ):
        names = re.findall(rf'EntityType Name="([^"]*{re.escape(needle.split("_")[-1])}[^"]*)"', meta)
        if not names:
            names = [m for m in re.findall(r'EntityType Name="([^"]+)"', meta) if needle in m]
        print(f"\nmetadata {needle}: {names[:8]}")

    # try register if published
    for reg in (
        "InformationRegister_ТД_ЗадачиПротоколов",
        "InformationRegister_ТД_ЗадачиОтдела",
    ):
        url = f"{base}/{reg}?$format=json&$top=3"
        rr = client.get(url)
        print(f"\n{reg}: HTTP {rr.status_code}")
        if rr.status_code == 200:
            vals = rr.json().get("value") or []
            print("rows", len(vals))
            if vals:
                print("keys", sorted(vals[0].keys())[:25])
                print(json.dumps(vals[0], ensure_ascii=False, indent=2)[:1500])
