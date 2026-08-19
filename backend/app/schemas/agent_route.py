from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentRouteSchema(BaseModel):
    handler: str = "generic"
    kind: str = ""
    mode: str = ""
    default_task: str = ""
    source: str = ""
    version: int = 1
    tools: list[str] = Field(default_factory=list)


class AgentRoutePatch(BaseModel):
    handler: str | None = None
    kind: str | None = None
    mode: str | None = None
    default_task: str | None = None
    tools: list[str] | None = None
    source: str = "api"
