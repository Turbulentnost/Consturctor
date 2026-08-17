from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TriggerCreate(BaseModel):
    workflow_id: str = ""
    message: str = ""
    at: datetime | None = None
    after_seconds: float | None = None
    condition: str = ""
    once: bool = True
    created_by_workflow_id: str = ""


class TriggerOut(BaseModel):
    id: str
    owner_user_id: str
    workflow_id: str
    created_by_workflow_id: str = ""
    message: str = ""
    condition_text: str = ""
    fire_at: datetime | None = None
    once: bool = True
    enabled: bool = True
    last_checked_at: datetime | None = None
    last_fired_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_evidence: str = ""
    created_at: datetime | None = None


class TriggerList(BaseModel):
    items: list[TriggerOut] = Field(default_factory=list)


class TriggerFiredAck(BaseModel):
    evidence: str = ""
