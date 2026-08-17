"""OData 402 diagnosis: auth + entities."""
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

base = env["ODATA_BASE_URL"].rstrip("/")
service = (env["ODATA_USERNAME"], env["ODATA_PASSWORD"])
user = (env.get("ERP_LOGIN", ""), env.get("ERP_PASSWORD", ""))
params = {"$format": "json", "$top": "2"}


def probe(label: str, entity: str, auth: tuple[str, str]) -> None:
    url = f"{base}/{entity}"
    r = httpx.get(url, params=params, auth=auth, timeout=45.0)
    print(f"\n=== {label} / {entity} ===")
    print("status", r.status_code)
    text = r.text.lstrip("\ufeff")
    try:
        data = json.loads(text)
        exc = data.get("exception") or data.get("#exception")
        if isinstance(data, dict) and "exception" in data:
            ex = data["exception"]
            print("reason", ex.get("reason"))
            print("desc", (ex.get("descr") or ex.get("desc") or "")[:300])
        elif "value" in data:
            print("rows", len(data["value"]))
        else:
            print(text[:400])
    except json.JSONDecodeError:
        print(text[:400])


for entity in (
    "Document_ТД_ВходящаяКорреспонденция",
    "BusinessProcess_Задание",
    "Catalog_КонтрагентыForMail",
):
    probe("service", entity, service)
    if user[0]:
        probe("user", entity, user)
