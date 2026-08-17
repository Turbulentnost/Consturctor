from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RunStatusEnum(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    HITL = "hitl"


class RunStartRequest(BaseModel):
    agent_id: str
    department: str = ""
    user_id: str = ""
    config: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)


class RunStatus(BaseModel):
    run_id: UUID
    agent_id: str
    department: str = ""
    user_id: str = ""
    status: RunStatusEnum
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    tool_events_count: int = 0
