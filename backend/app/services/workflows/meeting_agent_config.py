"""Unified hooks for specialized agents (artifact-close, SD, RK)."""

from __future__ import annotations

from typing import Any

from app.services.workflows.artifact_close_playbook import (
    apply_artifact_close_config,
    apply_artifact_close_plan_runtime,
    is_artifact_close_agent,
)
from app.services.workflows.rk_meeting_playbook import (
    apply_rk_config,
    apply_rk_plan_runtime,
    is_rk_meeting_agent,
)
from app.services.workflows.sd_meeting_playbook import (
    apply_sd_config,
    apply_sd_plan_runtime,
    is_sd_meeting_agent,
)


def is_meeting_agent(*parts: str) -> bool:
    blob = " ".join(str(part or "") for part in parts).strip()
    return (
        is_artifact_close_agent(blob)
        or is_rk_meeting_agent(blob)
        or is_sd_meeting_agent(blob)
    )


def refresh_meeting_agent_view(
    plan_json: dict[str, Any] | None,
    local_run: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
    document_text: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return plan/local_run with latest specialized playbook steps and tools (no DB write)."""
    blob = " ".join(part for part in (title, notes, document_text) if part).strip()
    if not is_meeting_agent(title, notes, blob):
        return dict(plan_json or {}), dict(local_run or {})
    plan = apply_meeting_plan_runtime(dict(plan_json or {}), title=title, notes=notes)
    local = apply_meeting_agent_config(dict(local_run or {}), title=title, notes=notes)
    draft = dict(local.get("playbook_draft") or {})
    if draft:
        draft["steps"] = plan.get("steps") or draft.get("steps") or []
        local["playbook_draft"] = draft
    return plan, local


def apply_meeting_agent_config(
    local_run: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
    document_text: str = "",
) -> dict[str, Any]:
    del document_text
    local = apply_artifact_close_config(local_run, title=title, notes=notes)
    if is_artifact_close_agent(title, notes):
        return local
    local = apply_rk_config(local, title=title, notes=notes)
    return apply_sd_config(local, title=title, notes=notes)


def apply_meeting_plan_runtime(
    plan_data: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
) -> dict[str, Any]:
    plan = apply_artifact_close_plan_runtime(plan_data, title=title, notes=notes)
    if is_artifact_close_agent(title, notes, (plan or {}).get("goal") or ""):
        return plan
    plan = apply_rk_plan_runtime(plan, title=title, notes=notes)
    return apply_sd_plan_runtime(plan, title=title, notes=notes)
