"""Live verify: onec.com.query_tasks via fixed COM module."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "platform-tool-onec-com"))

sys.stdout.reconfigure(encoding="utf-8")

env: dict[str, str] = {}
for line in (ROOT / "infra" / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    env[k.strip()] = v.strip().strip('"').strip("'")

for k, v in env.items():
    os.environ[k] = v

from platform_tool_onec_com.onec_com import (  # noqa: E402
    build_connection_string,
    connect_session,
    query_performer_tasks,
)

session = connect_session()
app = session["object"]
print("transport: com-connector")
print("progid:", session["progid"])
print("mode:", session["mode"])
print("connection:", build_connection_string().replace(env["ERP_PASSWORD"], "***"))
print("current_user:", session["current_user"])
rows = query_performer_tasks(app, mine_only=True, limit=20)
print("my_tasks:", len(rows))
for row in rows:
    print(f"  {row['number']} | {row['date'][:16]} | {row['description'][:70]}")
