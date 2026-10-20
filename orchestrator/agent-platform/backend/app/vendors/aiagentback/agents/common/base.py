from __future__ import annotations
import abc
from app.vendors.aiagentback.schemas.task import AgentResult
class BaseAgent(abc.ABC):
    agent_id: str = "base_agent"
    name: str = ""
    version: str = "0.1.0"
    purpose: str = ""
    allowed_tools: list[str] = []
    @abc.abstractmethod
    async def run(self, payload: dict) -> AgentResult:
        raise NotImplementedError
