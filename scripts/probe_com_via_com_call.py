"""Test COM connect via com_call (same path as HTTP service)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
import os

os.environ.setdefault("CONSTRUCTOR_ROOT", str(ROOT))

from platform_tool_onec_com.com_runtime import com_call
from platform_tool_onec_com.main import _load_infra_env
from platform_tool_onec_com.onec_com import connect_session, query_performer_tasks

_load_infra_env()
print("server", os.environ.get("ONEC_COM_SERVER"))
print("login", os.environ.get("ERP_LOGIN", "")[:20], "...")

session = com_call(connect_session, timeout=180)
print("connected", session.get("mode"), session.get("current_user"))
rows, src = com_call(
    lambda: query_performer_tasks(session["object"], mine_only=True, limit=10, prefer_crm=True),
    timeout=120,
)
print("source", src, "count", len(rows))
for row in rows[:5]:
    print(" ", row.get("number"), row.get("description", "")[:60])
