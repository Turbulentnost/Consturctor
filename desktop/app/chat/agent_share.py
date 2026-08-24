from __future__ import annotations

from typing import Any

from app.api_client import BoardAgent, WorkflowRecord


def agent_share_payload(agent: BoardAgent, record: WorkflowRecord | None = None) -> dict[str, Any]:
    """Snapshot another person needs to see and later import the agent."""
    goal = ""
    notes = ""
    tools: list[str] = []
    if record is not None:
        notes = (record.notes or "").strip()
        if record.plan is not None:
            goal = (record.plan.goal or "").strip()
        local = record.local_run if isinstance(record.local_run, dict) else {}
        raw_tools = local.get("tools")
        if isinstance(raw_tools, list):
            tools = [str(item) for item in raw_tools if str(item).strip()][:12]
        elif isinstance(raw_tools, dict):
            tools = [str(key) for key in raw_tools if str(key).strip()][:12]
    description = (agent.description or goal or notes).strip()
    return {
        "type": "agent_card",
        "workflow_id": agent.id,
        "title": (agent.title or (record.title if record else "") or "ИИ-агент").strip(),
        "description": description,
        "goal": goal or description,
        "trigger_summary": (agent.trigger_summary or "").strip(),
        "trigger_kind": (agent.trigger_kind or "").strip(),
        "status": agent.status or "active",
        "phase": agent.phase or (record.phase if record else "") or "done",
        "tools": tools,
    }
