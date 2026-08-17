"""Provider-agnostic LLM client with OpenAI and offline mock backends."""

from __future__ import annotations

import json
import logging
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from agent.types import AgentConfig, LLMResponse, Message, ToolCall

logger = logging.getLogger(__name__)


class LLMClient(ABC):
    @abstractmethod
    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        raise NotImplementedError


class OpenAIClient(LLMClient):
    def __init__(self, config: AgentConfig) -> None:
        if not config.api_key:
            raise ValueError("OPENAI_API_KEY (or AGENT_API_KEY) is required for OpenAI provider.")
        self.config = config
        self.base_url = (config.base_url or "https://api.openai.com/v1").rstrip("/")

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "tools": tools,
            "tool_choice": "auto",
        }
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=120.0) as client:
            response = client.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        choice = data["choices"][0]
        message = choice["message"]
        tool_calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            fn = item["function"]
            tool_calls.append(
                ToolCall(
                    id=item["id"],
                    name=fn["name"],
                    arguments=_parse_json(fn.get("arguments", "{}")),
                )
            )

        finish = choice.get("finish_reason", "stop")
        if tool_calls:
            finish = "tool_calls"
        return LLMResponse(content=message.get("content"), tool_calls=tool_calls, finish_reason=finish)


class MockLLMClient(LLMClient):
    """Scripted offline client for end-to-end demos without an API key."""

    HELLO_CONTENT = '''"""Simple add helper."""

def add(a: int, b: int) -> int:
    return a - b  # bug on purpose for str_replace demo


if __name__ == "__main__":
    print(add(2, 3))
'''

    TEST_CONTENT = '''from hello import add


def test_add():
    assert add(2, 3) == 5
'''

    def __init__(self) -> None:
        self._step = 0

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        del messages, tools
        steps = [
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="write_file",
                        arguments={"path": "examples/hello.py", "contents": self.HELLO_CONTENT},
                    ),
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="write_file",
                        arguments={"path": "examples/test_hello.py", "contents": self.TEST_CONTENT},
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="run_terminal",
                        arguments={"command": "py -3.12 -m pytest examples/test_hello.py -q", "timeout_ms": 60000},
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="read_file",
                        arguments={"path": "examples/hello.py"},
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="str_replace",
                        arguments={
                            "path": "examples/hello.py",
                            "old_string": "    return a - b  # bug on purpose for str_replace demo",
                            "new_string": "    return a + b",
                        },
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(
                        id=f"call_{uuid.uuid4().hex[:8]}",
                        name="run_terminal",
                        arguments={"command": "py -3.12 -m pytest examples/test_hello.py -q", "timeout_ms": 60000},
                    ),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                content="Created examples/hello.py with add(a,b), patched the bug via str_replace, and verified with pytest.",
                finish_reason="stop",
            ),
        ]
        if self._step >= len(steps):
            return LLMResponse(content="Mock scenario complete.", finish_reason="stop")
        response = steps[self._step]
        self._step += 1
        return response


def load_system_prompt() -> str:
    prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
    return prompt_path.read_text(encoding="utf-8")


def create_llm_client(config: AgentConfig) -> LLMClient:
    if config.provider == "mock" or not config.api_key:
        logger.info("Using MockLLMClient (no API key or provider=mock).")
        return MockLLMClient()
    if config.provider in {"openai", "default"}:
        return OpenAIClient(config)
    raise ValueError(f"Unsupported LLM provider: {config.provider}")


def load_config_from_env(workspace_root: str | None = None) -> AgentConfig:
    root = workspace_root or os.environ.get("AGENT_WORKSPACE", str(Path.cwd()))
    browser_enabled_raw = os.environ.get("AGENT_BROWSER_ENABLED", "true").lower()
    host_url = (
        os.environ.get("TOOL_DESKTOP_HOST_URL")
        or os.environ.get("TOOL_BROWSER_URL")
        or "http://127.0.0.1:7830"
    )
    platform_raw = os.environ.get("AGENT_PLATFORM_TOOLS", "false").lower()
    return AgentConfig(
        workspace_root=str(Path(root).resolve()),
        max_steps=int(os.environ.get("AGENT_MAX_STEPS", "25")),
        model=os.environ.get("AGENT_MODEL", os.environ.get("OPENAI_MODEL", "gpt-4o-mini")),
        api_key=os.environ.get("AGENT_API_KEY") or os.environ.get("OPENAI_API_KEY"),
        base_url=os.environ.get("AGENT_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
        provider=os.environ.get("AGENT_PROVIDER", "openai"),
        debug=os.environ.get("AGENT_DEBUG", "").lower() in {"1", "true", "yes"},
        browser_url=host_url.rstrip("/"),
        browser_enabled=browser_enabled_raw in {"1", "true", "yes"},
        platform_tools_enabled=platform_raw in {"1", "true", "yes"},
        platform_host_url=host_url.rstrip("/"),
    )


def _parse_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
