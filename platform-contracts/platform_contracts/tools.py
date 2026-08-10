from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ToolInvokeRequest(BaseModel):
    run_id: UUID | None = None
    department: str = ""
    user_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    ok: bool
    tool_name: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    audit_id: UUID | None = None


class ToolEvent(BaseModel):
    id: UUID | None = None
    run_id: UUID | None = None
    tool_name: str
    input_hash: str = ""
    output_summary: str = ""
    status: str = "ok"
    duration_ms: int = 0
    department: str = ""
