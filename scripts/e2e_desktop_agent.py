#!/usr/bin/env python3
"""E2E: agent run как из desktop (127.0.0.1:7812, auto_approve, SMART task)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))
os.environ["BACKEND_URL"] = "http://127.0.0.1:7812"

from app.api_client import ApiClient, ApiError  # noqa: E402

FIO = "Жалыбин Максим Дмитриевич"
PASSWORD = "gm360249"
TASK = (
    "Выгрузи реестр поручений ACT (Document_ТД_Поручения) из 1С через OData "
    "и сохрани Excel на рабочий стол с форматированием по каждому ACT00-***"
)
OUT = ROOT / "scripts" / "e2e_agent_result.json"


def main() -> int:
    client = ApiClient()
    health = client.health()
    print("health:", health.status, "llm:", health.llm_provider)

    try:
        client.login(FIO, PASSWORD)
    except ApiError as exc:
        print("login failed:", exc)
        return 1

    workflow_id = ""
    for item in client.list_workflows():
        blob = f"{item.title or ''}".casefold()
        if "act_porucheniya" in blob or "act00" in blob:
            continue
        if any(h in blob for h in ("smart", "porucheniya_smart", "регламент", "поруч")):
            workflow_id = str(item.id)
            if "smart" in blob:
                break
    if not workflow_id:
        for item in client.list_workflows():
            workflow_id = str(item.id)
            break
    if not workflow_id:
        print("no workflow")
        return 2

    print("workflow:", workflow_id)
    tools: list[str] = []
    messages: list[str] = []

    def on_event(p: dict) -> None:
        t = str(p.get("type") or "")
        if t == "tool_request":
            tool = str(p.get("tool") or "")
            tools.append(tool)
            print("TOOL_REQUEST:", tool)
        elif t in {"agent_message", "status", "error"}:
            text = str(p.get("text") or p.get("message") or "")
            if text:
                messages.append(f"[{t}] {text[:300]}")
                print(f"[{t}]", text[:200])

    result = client.stream_workflow_agent_run(
        workflow_id,
        TASK,
        on_event,
        source="app",
        auto_approve=True,
        agent_kind="act_porucheniya",
    )

    bad = "onec.search_documents" in tools
    ok_act = any(t in tools for t in ("excel.create_workbook",)) and any(
        m for m in messages if "ACT" in m or "act_porucheniya" in m.casefold() or "Поручения ACT" in m
    )

    payload = {
        "workflow_id": workflow_id,
        "tools": tools,
        "bad_search_documents": bad,
        "routing_ok": ok_act and not bad,
        "answer": (result or {}).get("answer", "")[:2000],
        "messages": messages[-12:],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print("written", OUT)
    print("routing_ok:", payload["routing_ok"])
    if bad:
        print("FAIL: still uses onec.search_documents")
        return 3
    print("answer:", payload["answer"][:500])
    return 0 if payload["routing_ok"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
