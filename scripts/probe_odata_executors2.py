#!/usr/bin/env python3
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

base = env["ODATA_BASE_URL"].rstrip("/")
auth = (env["ERP_LOGIN"], env["ERP_PASSWORD"])
user_key = "d30ccd95-84c9-11e3-9768-001e67112509"

with httpx.Client(auth=auth, timeout=90) as client:
    user = client.get(f"{base}/Catalog_Пользователи(guid'{user_key}')?$format=json").json()
    print("user Description:", user.get("Description"))
    fl_key = user.get("ФизическоеЛицо_Key")
    if fl_key:
        fl = client.get(f"{base}/Catalog_ФизическиеЛица(guid'{fl_key}')?$format=json")
        print("physical status", fl.status_code)
        if fl.status_code == 200:
            fd = fl.json()
            print("FIO:", fd.get("Description"), "|", fd.get("Наименование"))

    # batch: all ACT docs, collect unique responsible keys
    path = (
        "Document_ТД_Поручения?$format=json&$top=20"
        "&$filter=startswith(Number,'АСТ')&$orderby=Date desc"
    )
    docs = client.get(f"{base}/{path}").json().get("value") or []
    keys: set[str] = set()
    tasks = 0
    for doc in docs:
        for line in doc.get("Поручения") or []:
            tasks += 1
            k = str(line.get("ОтветственноеЛицо_Key") or "")
            if k and k != "00000000-0000-0000-0000-000000000000":
                keys.add(k)
    print(f"\n20 docs: {tasks} task lines, {len(keys)} unique ОтветственноеЛицо_Key")

    # resolve first 5 executors
    executors: dict[str, str] = {}
    for k in list(keys)[:8]:
        u = client.get(f"{base}/Catalog_Пользователи(guid'{k}')?$format=json")
        if u.status_code != 200:
            continue
        ud = u.json()
        name = str(ud.get("Description") or "")
        flk = ud.get("ФизическоеЛицо_Key")
        if flk:
            fl = client.get(f"{base}/Catalog_ФизическиеЛица(guid'{flk}')?$format=json")
            if fl.status_code == 200:
                name = str(fl.json().get("Description") or name)
        executors[k] = name
    print("executors sample:", json.dumps(executors, ensure_ascii=False, indent=2))

    # sample flat output
    print("\nflat sample:")
    for doc in docs[:3]:
        for line in doc.get("Поручения") or []:
            k = str(line.get("ОтветственноеЛицо_Key") or "")
            print(
                doc.get("Number"),
                "|",
                executors.get(k, k[:8]),
                "|",
                str(line.get("Мероприятие") or "")[:55],
                "|",
                str(line.get("СрокИсполнения") or "")[:10],
            )
