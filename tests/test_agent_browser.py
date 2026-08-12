from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from agent.llm_client import LLMClient
from agent.loop import run_agent
from agent.tool_registry import ToolContext, execute_tool, get_tool_schemas
from agent.tools.browser_client import BrowserToolClient
from agent.tools.todo_write import TodoStore
from agent.types import AgentConfig, LLMResponse, Message, ToolCall, ToolResult


class ScriptedLLM(LLMClient):
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self._i = 0

    def complete(self, messages: list[Message], tools: list[dict[str, Any]]) -> LLMResponse:
        del messages, tools
        if self._i >= len(self._responses):
            return LLMResponse(content="done", finish_reason="stop")
        resp = self._responses[self._i]
        self._i += 1
        return resp


class FakeBrowserClient(BrowserToolClient):
    def __init__(self) -> None:
        super().__init__(base_url="http://browser.test")
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self.closed: list[str] = []
        self._open: set[str] = set()
        self._url: dict[str, str] = {}

    def invoke(self, tool_name: str, run_id: str, payload: dict[str, Any] | None = None) -> ToolResult:
        payload = payload or {}
        self.calls.append((tool_name, run_id, payload))
        if tool_name == "browser.open_session":
            self._open.add(run_id)
            return ToolResult.success(tool_name, {"summary": "open", "run_id": run_id, "stub": True})
        if tool_name == "browser.close_session":
            self.closed.append(run_id)
            self._open.discard(run_id)
            return ToolResult.success(tool_name, {"summary": "closed", "run_id": run_id, "closed": True})
        if tool_name == "browser.navigate":
            self._url[run_id] = str(payload.get("url", ""))
            return ToolResult.success(
                tool_name,
                {"summary": "nav", "run_id": run_id, "url": self._url[run_id], "title": "Fake"},
            )
        if tool_name == "browser.extract_text":
            return ToolResult.success(
                tool_name,
                {
                    "summary": "text",
                    "run_id": run_id,
                    "url": self._url.get(run_id, ""),
                    "text": "hello from page",
                },
            )
        return ToolResult.success(tool_name, {"summary": tool_name, "run_id": run_id})


def test_browser_schemas_include_session_tools() -> None:
    names = {s["function"]["name"] for s in get_tool_schemas(browser_enabled=True)}
    assert "browser.open_session" in names
    assert "browser.snapshot" in names
    assert "browser.type" in names
    assert "write_file" in names
    assert "browser.open_session" not in {s["function"]["name"] for s in get_tool_schemas(browser_enabled=False)}


def test_browser_autowire_without_explicit_client(tmp_path: Path, monkeypatch) -> None:
    fake = FakeBrowserClient()

    def _factory(url: str = "http://127.0.0.1:7824", timeout_sec: float = 60.0):
        del url, timeout_sec
        return fake

    monkeypatch.setattr("agent.tool_registry.BrowserToolClient", _factory)
    config = AgentConfig(workspace_root=str(tmp_path), browser_enabled=True, browser_url="http://browser.test")
    ctx = ToolContext(config=config, todo_store=TodoStore())  # browser=None on purpose
    result = execute_tool(ctx, "browser.open_session", {})
    assert result.ok is True
    assert ctx.browser is fake
    assert any(c[0] == "browser.open_session" for c in fake.calls)


def test_execute_browser_tools_via_client(tmp_path: Path) -> None:
    fake = FakeBrowserClient()
    run_id = str(uuid4())
    config = AgentConfig(
        workspace_root=str(tmp_path),
        max_steps=10,
        browser_enabled=True,
        browser_url="http://browser.test",
        run_id=run_id,
    )
    ctx = ToolContext(config=config, todo_store=TodoStore(), run_id=run_id, browser=fake)
    assert execute_tool(ctx, "browser.open_session", {}).ok
    assert execute_tool(ctx, "browser.navigate", {"url": "https://example.com"}).ok
    extracted = execute_tool(ctx, "browser.extract_text", {})
    assert extracted.ok
    assert extracted.data["text"] == "hello from page"


def test_run_agent_closes_browser_session(tmp_path: Path, monkeypatch) -> None:
    fake = FakeBrowserClient()
    closed: list[str] = []

    class TrackingClient(FakeBrowserClient):
        def close_session(self, run_id: str) -> ToolResult:
            closed.append(run_id)
            return super().close_session(run_id)

    tracking = TrackingClient()

    def _factory(url: str = "http://127.0.0.1:7824", timeout_sec: float = 60.0):
        del url, timeout_sec
        return tracking

    monkeypatch.setattr("agent.loop.BrowserToolClient", _factory)

    run_id = str(uuid4())
    config = AgentConfig(
        workspace_root=str(tmp_path),
        max_steps=5,
        browser_enabled=True,
        run_id=run_id,
    )
    llm = ScriptedLLM(
        [
            LLMResponse(
                tool_calls=[ToolCall(id="1", name="browser.open_session", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[
                    ToolCall(id="2", name="browser.navigate", arguments={"url": "https://example.com"}),
                ],
                finish_reason="tool_calls",
            ),
            LLMResponse(
                tool_calls=[ToolCall(id="3", name="browser.extract_text", arguments={})],
                finish_reason="tool_calls",
            ),
            LLMResponse(content="Extracted: hello from page", finish_reason="stop"),
        ]
    )
    result = run_agent("browser smoke", config, llm)
    assert result.aborted is False
    assert "hello from page" in (result.final_answer or "")
    assert closed == [run_id]
    assert any(c[0] == "browser.navigate" for c in tracking.calls)
