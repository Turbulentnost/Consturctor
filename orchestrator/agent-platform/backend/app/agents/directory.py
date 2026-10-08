"""Все агенты стенда: зарегистрированные локально и опубликованные в Constructor."""

from __future__ import annotations

from app.agents.registry import AgentSpec, get_agent, list_agents
from app.constructor.catalog import constructor_catalog


def constructor_agents() -> list[AgentSpec]:
    return [
        AgentSpec(
            id=agent.id,
            title=agent.title,
            description=agent.description,
            tool_names=agent.tools,
            source="constructor",
            owner_id=owner.id,
            owner_fio=owner.fio,
        )
        for owner in constructor_catalog.owners()
        for agent in owner.agents
    ]


def all_agents() -> list[AgentSpec]:
    return list_agents() + constructor_agents()


def find_agent(agent_id: str) -> AgentSpec | None:
    local = get_agent(agent_id)
    if local is not None:
        return local
    return next((item for item in constructor_agents() if item.id == agent_id), None)
