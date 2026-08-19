#!/usr/bin/env python3
"""Smoke: fetch ACT registry via OData module."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

sys.path.insert(0, str(ROOT / "backend"))
from app.services.act_porucheniya_odata import fetch_act_porucheniya_registry

payload = fetch_act_porucheniya_registry(limit=5)
print(payload["summary"])
for doc in payload.get("documents") or []:
    print(doc["number_display"], "|", doc["about"][:50], "|", doc["reporter"])
