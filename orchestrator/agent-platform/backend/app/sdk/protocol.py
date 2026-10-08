"""Построчный JSON между Python и локальным runner @cursor/sdk.

Совпадает с командами desktop/sdk-agent Constructor: одна JSON-строка на сообщение.
Поля сериализуются в camelCase, как их ждёт Node-runner.
Сам runner сюда ещё не перенесён.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SdkModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class ModelParam(SdkModel):
    id: str
    value: str


class SdkToolSpec(SdkModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="inputSchema")
    timeout_seconds: int = Field(default=90, alias="timeoutSeconds")


class RunCommand(SdkModel):
    type: Literal["run"] = "run"
    id: str
    prompt: str
    model: str = "grok-4.6"
    model_params: list[ModelParam] = Field(default_factory=list, alias="modelParams")
    cwd: str = ""
    mode: Literal["design", "run", "interview", "kpi"] = "run"
    use_tools: bool = Field(default=True, alias="useTools")
    tools: list[SdkToolSpec] = Field(default_factory=list)


class ToolRequestEvent(SdkModel):
    """Runner просит Python исполнить инструмент и ждёт ToolResultCommand с тем же requestId."""

    type: Literal["tool_request"] = "tool_request"
    request_id: str = Field(alias="requestId")
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResultCommand(SdkModel):
    type: Literal["tool_result"] = "tool_result"
    request_id: str = Field(alias="requestId")
    ok: bool = True
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


def dump_command(command: RunCommand | ToolResultCommand) -> dict[str, Any]:
    return command.model_dump(by_alias=True, exclude_none=True)
