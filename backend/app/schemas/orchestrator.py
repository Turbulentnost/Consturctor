from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.workflow import KpiTileSchema


class OrchestratorAgentBrief(BaseModel):
    id: str = ""
    title: str = ""
    goal: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)


class OrchestratorUserBrief(BaseModel):
    id: str = ""
    fio: str = ""
    position: str = ""


class OrchestratorOut(BaseModel):
    status: str = "empty"
    locked: bool = False
    summary: str = ""
    tiles: list[KpiTileSchema] = Field(default_factory=list)
    source_fingerprint: str = ""
    current_fingerprint: str = ""
    source_agent_ids: list[str] = Field(default_factory=list)
    needs_form: bool = False
    needs_calc: bool = False
    due_tile_ids: list[str] = Field(default_factory=list)
    sdk_agent_id: str = ""
    formed_at: str = ""
    form_prompt: str = ""
    calc_prompt: str = ""
    agents: list[OrchestratorAgentBrief] = Field(default_factory=list)
    user: OrchestratorUserBrief = Field(default_factory=OrchestratorUserBrief)


class OrchestratorEnsureIn(BaseModel):
    mode: str = "form"


class OrchestratorSaveIn(BaseModel):
    summary: str = ""
    tiles: list[dict[str, Any]] = Field(default_factory=list)
    sdk_agent_id: str = ""


class OrchestratorPatchIn(BaseModel):
    tiles: list[dict[str, Any]] = Field(default_factory=list)
    sdk_agent_id: str = ""
