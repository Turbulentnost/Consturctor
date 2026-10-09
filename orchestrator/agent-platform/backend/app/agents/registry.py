"""Каталог агентов стенда.

Реализации из Constructor сюда не переносятся.
Когда агент появится, его модуль вызывает register_agent() из catalog.load().
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AgentSpec(BaseModel):
    id: str
    title: str
    description: str = ""
    model: str = "grok-4.6"
    modes: list[str] = Field(default_factory=lambda: ["run"])
    tool_names: list[str] = Field(default_factory=list)
    source: Literal["local", "constructor"] = "local"
    owner_id: str = ""
    owner_fio: str = ""


_AGENTS: list[AgentSpec] = []


def register_agent(spec: AgentSpec) -> None:
    if any(item.id == spec.id for item in _AGENTS):
        raise ValueError(f"agent already registered: {spec.id}")
    _AGENTS.append(spec)


def get_agent(agent_id: str) -> AgentSpec | None:
    for item in _AGENTS:
        if item.id == agent_id:
            return item
    return None


def list_agents() -> list[AgentSpec]:
    return list(_AGENTS)


def load_catalog() -> None:
    from app.agents.catalog import load

    load()
