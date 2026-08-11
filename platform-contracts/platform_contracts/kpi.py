from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewEventCreate(BaseModel):
    run_id: UUID | None = None
    actor: str = "operator"
    event_type: str
    category: str = "general"
    old_value: str | None = None
    new_value: str | None = None
    source: str = "api"
    department: str = ""


class ReviewEvent(ReviewEventCreate):
    id: UUID
    created_at: datetime


class KpiSummary(BaseModel):
    period_start: datetime | None = None
    period_end: datetime | None = None
    total_runs: int = 0
    success_rate: float = 0.0
    error_rate: float = 0.0
    hitl_rate: float = 0.0
    operator_keep_rate: float | None = None
    tool_failure_rate: float = 0.0
    operator_saved: int = 0
    operator_changed: int = 0
    tool_invocations: int = 0
    tool_failures: int = 0
    tasks_correct: int = 0
    tasks_total: int = 0
    tasks_lifetime_total: int = 0
    task_success_rate: float = 0.0
    by_department: dict[str, Any] = Field(default_factory=dict)
