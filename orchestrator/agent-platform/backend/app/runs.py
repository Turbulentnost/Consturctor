"""Записи прогонов стенда. Хранятся в памяти процесса."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from app.agents.registry import AgentSpec
from app.sdk.protocol import RunCommand, SdkToolSpec
from app.sdk.runner import SdkNotConnected, start_run
from app.tools.registry import get_tool


class RunRecord(BaseModel):
    id: str
    agent_id: str
    prompt: str
    tool_names: list[str] = Field(default_factory=list)
    status: str
    message: str = ""
    created_at: str


_RUNS: list[RunRecord] = []


def list_runs() -> list[RunRecord]:
    return list(reversed(_RUNS))


def create_run(agent: AgentSpec, prompt: str, tool_names: list[str]) -> RunRecord:
    names = tool_names or list(agent.tool_names)
    tools: list[SdkToolSpec] = []
    for name in names:
        spec = get_tool(name)
        if spec is None or not spec.available:
            continue
        tools.append(
            SdkToolSpec(
                name=spec.name,
                description=spec.description,
                input_schema=spec.input_schema,
                timeout_seconds=spec.timeout_seconds,
            )
        )
    command = RunCommand(
        id=str(uuid4()),
        prompt=prompt,
        model=agent.model,
        use_tools=bool(tools),
        tools=tools,
    )
    try:
        start_run(command)
    except SdkNotConnected as exc:
        status = "sdk_not_connected"
        message = str(exc)
    else:
        status = "started"
        message = ""
    record = RunRecord(
        id=command.id,
        agent_id=agent.id,
        prompt=prompt,
        tool_names=names,
        status=status,
        message=message,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _RUNS.append(record)
    return record
