"""Quick OData URL probe."""
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

base = env["ODATA_BASE_URL"].rstrip("/")
auth = (env["ODATA_USERNAME"], env["ODATA_PASSWORD"])
entity = "Document_ТД_ВходящаяКорреспонденция"

for label, suffix in [
    ("bare", ""),
    ("top_only", "?$top=3"),
    ("full", "?$format=json&$top=3"),
]:
    url = f"{base}/{entity}{suffix}"
    r = httpx.get(url, auth=auth, timeout=45.0)
    print(label, r.status_code, r.text[:150].replace("\n", " "))
