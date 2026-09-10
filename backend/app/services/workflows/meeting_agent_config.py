"""Unified hooks for specialized meeting agents (SD, RK)."""

from __future__ import annotations

from typing import Any

from app.services.workflows.rk_meeting_playbook import apply_rk_config, apply_rk_plan_runtime
from app.services.workflows.sd_meeting_playbook import apply_sd_config, apply_sd_plan_runtime


def apply_meeting_agent_config(
    local_run: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
) -> dict[str, Any]:
    local = apply_rk_config(local_run, title=title, notes=notes)
    return apply_sd_config(local, title=title, notes=notes)


def apply_meeting_plan_runtime(
    plan_data: dict[str, Any] | None,
    *,
    title: str,
    notes: str,
) -> dict[str, Any]:
    plan = apply_rk_plan_runtime(plan_data, title=title, notes=notes)
    return apply_sd_plan_runtime(plan, title=title, notes=notes)
