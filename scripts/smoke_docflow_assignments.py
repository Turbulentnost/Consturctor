"""Smoke test docflow COM query."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "platform-tool-onec-com"))
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

from platform_tool_onec_com.onec_com import connect_session, query_docflow_assignments  # noqa: E402

session = connect_session()
rows = query_docflow_assignments(session["object"], user_name=os.environ["ERP_LOGIN"], limit=20)
print("direct COM rows:", len(rows))
for row in rows[:5]:
    print(json.dumps(row, ensure_ascii=False))

try:
    req = urllib.request.Request(
        "http://127.0.0.1:7831/api/v1/tools/onec.com.query_docflow_assignments/invoke",
        data=json.dumps(
            {"run_id": "smoke", "payload": {"fio": os.environ["ERP_LOGIN"], "limit": 20}}
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    print("http ok:", data.get("ok"), "count:", (data.get("data") or {}).get("count"))
except Exception as exc:
    print("http FAIL:", exc)
