from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TriggerCreate(BaseModel):
    workflow_id: str = ""
    message: str = ""
    at: datetime | None = None
    after_seconds: float | None = None
    interval_seconds: float | None = None
    condition: str = ""
    once: bool = True
    created_by_workflow_id: str = ""
    # Optional recurrence constraints (MSK). active_days: 0=Mon..6=Sun, empty=every day.
    active_days: list[int] = Field(default_factory=list)
    window_start: str = ""  # "HH:MM"
    window_end: str = ""  # "HH:MM"


class TriggerOut(BaseModel):
    id: str
    owner_user_id: str
    workflow_id: str
    created_by_workflow_id: str = ""
    message: str = ""
    condition_text: str = ""
    fire_at: datetime | None = None
    interval_seconds: int = 0
    once: bool = True
    enabled: bool = True
    last_checked_at: datetime | None = None
    last_fired_at: datetime | None = None
    cooldown_until: datetime | None = None
    last_evidence: str = ""
    created_at: datetime | None = None
    active_days: list[int] = Field(default_factory=list)
    window_start: str = ""
    window_end: str = ""


class TriggerList(BaseModel):
    items: list[TriggerOut] = Field(default_factory=list)


class TriggerFiredAck(BaseModel):
    evidence: str = ""


class TriggerSkipSlot(BaseModel):
    at: datetime


class ScheduleTriggerSpec(BaseModel):
    kind: str = "event"
    message: str = ""
    interval_value: float = 0
    interval_unit: str = "hours"
    condition: str = ""
    at: str = ""
    once: bool = True
    # Recurrence constraints for interval triggers (MSK).
    weekdays: list[int] = Field(default_factory=list)  # 0=Mon..6=Sun, empty=every day
    window_start: str = ""  # "HH:MM"
    window_end: str = ""  # "HH:MM"


class ScheduleDraftOut(BaseModel):
    name: str = ""
    goal: str = ""
    triggers: list[ScheduleTriggerSpec] = Field(default_factory=list)
