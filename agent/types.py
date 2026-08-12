"""Shared types for the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolError:
    code: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass
class ToolResult:
    ok: bool
    tool: str
    data: dict[str, Any] | None = None
    error: ToolError | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "data": self.data,
            "error": self.error.to_dict() if self.error else None,
        }

    @staticmethod
    def success(tool: str, data: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, tool=tool, data=data)

    @staticmethod
    def failure(tool: str, code: str, message: str) -> ToolResult:
        return ToolResult(ok=False, tool=tool, error=ToolError(code=code, message=message))


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Literal["stop", "tool_calls", "length", "error"] = "stop"


@dataclass
class Message:
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            payload["content"] = self.content
        if self.tool_calls is not None:
            payload["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": _serialize_arguments(call.arguments),
                    },
                }
                for call in self.tool_calls
            ]
        if self.tool_call_id is not None:
            payload["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            payload["name"] = self.name
        return payload


@dataclass
class AgentConfig:
    workspace_root: str
    max_steps: int = 25
    model: str = "gpt-4o-mini"
    api_key: str | None = None
    base_url: str | None = None
    provider: str = "openai"
    debug: bool = False
    max_file_write_bytes: int = 512_000
    max_output_bytes: int = 256_000
    browser_url: str = "http://127.0.0.1:7824"
    browser_enabled: bool = True
    run_id: str | None = None


@dataclass
class AgentRunResult:
    final_answer: str | None
    steps: int
    messages: list[Message]
    aborted: bool = False
    abort_reason: str | None = None


def _serialize_arguments(arguments: dict[str, Any]) -> str:
    import json

    return json.dumps(arguments, ensure_ascii=False)
