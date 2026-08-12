from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class CronTemplateInfo(BaseModel):
    id: str
    title: str
    description: str
    default_cron: str
    default_agent_id: str
    config_schema: dict[str, Any] = Field(default_factory=dict)


class CronJobCreate(BaseModel):
    name: str
    description: str = ""
    template_id: str = "custom"
    agent_id: str = ""
    department: str = ""
    user_id: str = ""
    cron_expr: str = ""
    timezone: str = "Europe/Moscow"
    enabled: bool = True
    config: dict[str, Any] = Field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


class CronJobUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cron_expr: str | None = None
    timezone: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None


class CronJobOut(BaseModel):
    id: UUID
    name: str
    description: str
    template_id: str
    agent_id: str
    department: str
    user_id: str
    cron_expr: str
    timezone: str
    enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    last_run_at: datetime | None = None
    last_run_id: UUID | None = None
    next_run_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
