from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PositionKpiTileOut(BaseModel):
    code: str
    name: str
    weight: int = 0
    unit: str = "%"
    plan: int | None = None
    fact: float | None = None
    score: float | None = None
    contrib: float | None = None
    evidence: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class PositionKpiSubjectOut(BaseModel):
    fio: str
    position: str


class PositionKpiDailyOut(BaseModel):
    position: str
    profile_id: str
    period_from: str
    period_to: str
    as_of: str
    computed_at: str
    cached: bool = False
    stale: bool = False
    tiles: list[PositionKpiTileOut] = Field(default_factory=list)


class PositionKpiBuildCreate(BaseModel):
    position: str = ""


class PositionKpiBuildTurnIn(BaseModel):
    message: str = ""


class PositionKpiBuildSdkFinishIn(BaseModel):
    answer: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)
    modules: list[dict[str, Any]] = Field(default_factory=list)
    catalog_draft: dict[str, Any] = Field(default_factory=dict)
    cursor_agent_id: str = ""
    connect: bool = False


class PositionKpiBuildConnectIn(BaseModel):
    catalog_draft: dict[str, Any] = Field(default_factory=dict)
    modules: list[dict[str, Any]] = Field(default_factory=list)


class PositionKpiBuildMessageOut(BaseModel):
    message_id: str
    role: str
    content: str = ""
    structured: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class PositionKpiBuildOut(BaseModel):
    build_id: str
    position: str
    status: str
    cursor_agent_id: str = ""
    extracted: dict[str, Any] = Field(default_factory=dict)
    catalog_draft: dict[str, Any] = Field(default_factory=dict)
    modules: list[dict[str, Any]] = Field(default_factory=list)
    profile_id: str = ""
    sdk_prompt: str = ""
    messages: list[PositionKpiBuildMessageOut] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
