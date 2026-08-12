"""Tests for the Constructor agent runtime."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.llm_client import MockLLMClient, create_llm_client, load_config_from_env
from agent.loop import run_agent
from agent.safety import SafetyError, resolve_workspace_path
from agent.tool_registry import ToolContext, execute_tool
from agent.tools.todo_write import TodoStore
from agent.types import AgentConfig


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def config(workspace: Path) -> AgentConfig:
    return AgentConfig(workspace_root=str(workspace), max_steps=10)


@pytest.fixture
def ctx(config: AgentConfig) -> ToolContext:
    return ToolContext(config=config, todo_store=TodoStore())


def test_write_file_creates_py(ctx: ToolContext) -> None:
    result = execute_tool(ctx, "write_file", {"path": "hello.py", "contents": "def add(a, b):\n    return a + b\n"})
    assert result.ok is True
    assert (Path(ctx.config.workspace_root) / "hello.py").is_file()


def test_str_replace_patches_function(ctx: ToolContext) -> None:
    execute_tool(ctx, "write_file", {"path": "hello.py", "contents": "def add(a, b):\n    return a - b\n"})
    result = execute_tool(
        ctx,
        "str_replace",
        {"path": "hello.py", "old_string": "return a - b", "new_string": "return a + b"},
    )
    assert result.ok is True
    text = (Path(ctx.config.workspace_root) / "hello.py").read_text(encoding="utf-8")
    assert "return a + b" in text


def test_grep_finds_symbol(ctx: ToolContext) -> None:
    execute_tool(ctx, "write_file", {"path": "mod.py", "contents": "def add(a, b):\n    pass\n"})
    result = execute_tool(ctx, "grep", {"pattern": r"def add", "path": "mod.py"})
    assert result.ok is True
    assert result.data["count"] == 1


def test_glob_finds_py(ctx: ToolContext) -> None:
    execute_tool(ctx, "write_file", {"path": "pkg/a.py", "contents": "x = 1\n"})
    result = execute_tool(ctx, "glob", {"pattern": "**/*.py"})
    assert result.ok is True
    assert "pkg/a.py" in result.data["matches"]


def test_run_terminal_python(ctx: ToolContext) -> None:
    execute_tool(ctx, "write_file", {"path": "runme.py", "contents": "print('ok')\n"})
    result = execute_tool(ctx, "run_terminal", {"command": "py -3.12 runme.py"})
    assert result.ok is True
    assert result.data["exit_code"] == 0
    assert "ok" in result.data["stdout"]


def test_write_outside_workspace_rejected(config: AgentConfig) -> None:
    with pytest.raises(SafetyError) as exc:
        resolve_workspace_path(config.workspace_root, "../../outside.txt")
    assert exc.value.code == "path_outside_workspace"


def test_shell_write_blocked(ctx: ToolContext) -> None:
    result = execute_tool(ctx, "run_terminal", {"command": "echo hi > blocked.txt"})
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "command_denied"


def test_mock_e2e_hello_demo(workspace: Path) -> None:
    config = AgentConfig(workspace_root=str(workspace), max_steps=20, provider="mock")
    llm = MockLLMClient()
    result = run_agent("hello demo", config, llm)
    assert result.aborted is False
    hello = workspace / "examples" / "hello.py"
    test = workspace / "examples" / "test_hello.py"
    assert hello.is_file()
    assert test.is_file()
    assert "return a + b" in hello.read_text(encoding="utf-8")

    run = execute_tool(
        ToolContext(config=config, todo_store=TodoStore()),
        "run_terminal",
        {"command": "py -3.12 -m pytest examples/test_hello.py -q", "timeout_ms": 60000},
    )
    assert run.ok is True
    assert run.data["exit_code"] == 0


def test_create_llm_client_mock_without_key(config: AgentConfig) -> None:
    config.api_key = None
    client = create_llm_client(config)
    assert client.__class__.__name__ == "MockLLMClient"
