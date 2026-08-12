"""Tool schemas and execution dispatch."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable
from uuid import uuid4

from agent.tools.browser_client import BROWSER_READ_ONLY, BROWSER_TOOLS, BrowserToolClient
from agent.tools.delete_file import delete_file
from agent.tools.glob_files import glob_files
from agent.tools.grep_search import grep_search
from agent.tools.platform_client import PLATFORM_TOOL_NAMES, PlatformToolClient
from agent.tools.read_file import read_file
from agent.tools.read_lints import read_lints
from agent.tools.run_terminal import run_terminal
from agent.tools.str_replace import str_replace
from agent.tools.todo_write import TodoStore, todo_write
from agent.tools.web_fetch import web_fetch
from agent.tools.write_file import write_file
from agent.types import AgentConfig, ToolResult

READ_ONLY_TOOLS = frozenset({"read_file", "glob", "grep", "read_lints"}) | BROWSER_READ_ONLY


@dataclass
class ToolContext:
    config: AgentConfig
    todo_store: TodoStore
    run_id: str = field(default_factory=lambda: str(uuid4()))
    browser: BrowserToolClient | None = None
    platform: PlatformToolClient | None = None


Handler = Callable[[ToolContext, dict[str, Any]], ToolResult]


def _schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


_CORE_SCHEMAS: list[dict[str, Any]] = [
    _schema(
        "read_file",
        "Read a UTF-8 text file. Use offset/limit for large files. Always read before editing.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path relative to workspace root."},
                "offset": {"type": "integer", "description": "1-based start line (optional)."},
                "limit": {"type": "integer", "description": "Maximum number of lines to return (optional)."},
            },
            "required": ["path"],
        },
    ),
    _schema(
        "write_file",
        "Create or overwrite a file. Never use shell redirection for source edits.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "contents": {"type": "string"},
            },
            "required": ["path", "contents"],
        },
    ),
    _schema(
        "str_replace",
        "Replace an exact unique snippet in a file (preferred edit method for existing files).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "new_string": {"type": "string"},
                "replace_all": {"type": "boolean", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
    ),
    _schema(
        "delete_file",
        "Delete a file within the workspace.",
        {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    ),
    _schema(
        "glob",
        "Find files by glob pattern. Skips .git, node_modules, venv, __pycache__, dist, build.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern, e.g. **/*.py"},
                "target_directory": {"type": "string", "description": "Directory to search (default: workspace root)."},
            },
            "required": ["pattern"],
        },
    ),
    _schema(
        "grep",
        "Search file contents with a regex. Returns path:line:content matches.",
        {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "File or directory to search."},
                "glob": {"type": "string", "description": "Optional filename glob filter."},
                "case_insensitive": {"type": "boolean", "default": False},
                "head_limit": {"type": "integer"},
                "context_before": {"type": "integer", "description": "Lines before match (rg only)."},
                "context_after": {"type": "integer", "description": "Lines after match (rg only)."},
            },
            "required": ["pattern"],
        },
    ),
    _schema(
        "run_terminal",
        "Run shell commands for run/test/build/git only. NOT for writing or patching source files. NOT for browsing the web.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string"},
                "timeout_ms": {"type": "integer"},
                "env": {"type": "object", "additionalProperties": {"type": "string"}},
            },
            "required": ["command"],
        },
    ),
    _schema(
        "read_lints",
        "Read linter diagnostics via ruff when installed.",
        {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}},
            },
        },
    ),
    _schema(
        "web_fetch",
        "Fetch readable text from an allowlisted URL via desktop host browser worker.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
            },
            "required": ["url"],
        },
    ),
    _schema(
        "todo_write",
        "Track multi-step task progress.",
        {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed", "cancelled"],
                            },
                        },
                        "required": ["id", "content", "status"],
                    },
                },
                "merge": {"type": "boolean", "default": True},
            },
        },
    ),
]

_BROWSER_SCHEMAS: list[dict[str, Any]] = [
    _schema(
        "browser.open_session",
        "Open an ephemeral browser session for this agent run (cookies die when closed).",
        {"type": "object", "properties": {}},
    ),
    _schema(
        "browser.close_session",
        "Destroy the ephemeral browser session (tabs/cookies).",
        {"type": "object", "properties": {}},
    ),
    _schema(
        "browser.navigate",
        "Navigate the active tab to a URL (must be allowlisted on the worker).",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "timeout_ms": {"type": "integer"},
            },
            "required": ["url"],
        },
    ),
    _schema(
        "browser.snapshot",
        "Return interactive elements with ref/role/name/selector. Call before click/type.",
        {"type": "object", "properties": {}},
    ),
    _schema(
        "browser.click",
        "Click an element by CSS selector or snapshot ref on the current page (does not reopen a new session).",
        {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "ref": {"type": "string", "description": "Element ref from browser.snapshot (e.g. e3)."},
                "timeout_ms": {"type": "integer"},
            },
        },
    ),
    _schema(
        "browser.type",
        "Type text into an input. Prefer after snapshot. Use submit=true to press Enter.",
        {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "ref": {"type": "string"},
                "text": {"type": "string"},
                "clear": {"type": "boolean", "default": True},
                "submit": {"type": "boolean", "default": False},
                "password": {"type": "boolean", "default": False},
                "timeout_ms": {"type": "integer"},
            },
            "required": ["text"],
        },
    ),
    _schema(
        "browser.fill",
        "Fill an input completely (clear + type).",
        {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "ref": {"type": "string"},
                "text": {"type": "string"},
                "submit": {"type": "boolean", "default": False},
                "timeout_ms": {"type": "integer"},
            },
            "required": ["text"],
        },
    ),
    _schema(
        "browser.wait",
        "Wait for selector/ref, URL pattern, or sleep_ms.",
        {
            "type": "object",
            "properties": {
                "selector": {"type": "string"},
                "ref": {"type": "string"},
                "url": {"type": "string"},
                "sleep_ms": {"type": "integer"},
                "timeout_ms": {"type": "integer"},
            },
        },
    ),
    _schema(
        "browser.tabs",
        "List/create/switch tabs. action=list|new|switch.",
        {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "new", "switch"], "default": "list"},
                "page_id": {"type": "string"},
                "url": {"type": "string"},
            },
        },
    ),
    _schema(
        "browser.screenshot",
        "Capture screenshot of the active page into workspace screenshots.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Optional; navigate first if page blank."},
                "full_page": {"type": "boolean", "default": False},
            },
        },
    ),
    _schema(
        "browser.extract_text",
        "Extract text from the active page, a URL, or DuckDuckGo search via query.",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "query": {"type": "string"},
                "selector": {"type": "string", "default": "body"},
                "max_results": {"type": "integer"},
                "fetch_first": {"type": "boolean", "default": True},
            },
        },
    ),
]

# Backward-compatible export used by loop/tests
TOOL_SCHEMAS: list[dict[str, Any]] = _CORE_SCHEMAS + _BROWSER_SCHEMAS


def get_tool_schemas(*, browser_enabled: bool = True, platform_tools_enabled: bool = False) -> list[dict[str, Any]]:
    schemas = list(_CORE_SCHEMAS)
    if browser_enabled:
        schemas.extend(_BROWSER_SCHEMAS)
    if platform_tools_enabled:
        schemas.extend(_platform_schemas())
    return schemas


def _platform_schemas() -> list[dict[str, Any]]:
    return [
        _schema(
            name,
            f"Platform tool via desktop host :7830 — {name}",
            {"type": "object", "properties": {"payload": {"type": "object"}}, "additionalProperties": True},
        )
        for name in sorted(PLATFORM_TOOL_NAMES)
    ]


def _handle_read_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return read_file(
        ctx.config.workspace_root,
        args["path"],
        offset=args.get("offset"),
        limit=args.get("limit"),
    )


def _handle_write_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return write_file(
        ctx.config.workspace_root,
        args["path"],
        args["contents"],
        ctx.config.max_file_write_bytes,
    )


def _handle_str_replace(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return str_replace(
        ctx.config.workspace_root,
        args["path"],
        args["old_string"],
        args["new_string"],
        replace_all=bool(args.get("replace_all", False)),
    )


def _handle_delete_file(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return delete_file(ctx.config.workspace_root, args["path"])


def _handle_glob(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return glob_files(
        ctx.config.workspace_root,
        args["pattern"],
        target_directory=args.get("target_directory"),
    )


def _handle_grep(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return grep_search(
        ctx.config.workspace_root,
        args["pattern"],
        path=args.get("path"),
        glob=args.get("glob"),
        case_insensitive=bool(args.get("case_insensitive", False)),
        head_limit=args.get("head_limit"),
        context_before=args.get("context_before"),
        context_after=args.get("context_after"),
    )


def _handle_run_terminal(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return run_terminal(
        ctx.config.workspace_root,
        args["command"],
        cwd=args.get("cwd"),
        timeout_ms=args.get("timeout_ms"),
        env=args.get("env"),
        max_output_bytes=ctx.config.max_output_bytes,
    )


def _handle_read_lints(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return read_lints(ctx.config.workspace_root, args.get("paths"))


def _handle_todo_write(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return todo_write(ctx.todo_store, todos=args.get("todos"), merge=bool(args.get("merge", True)))


def _handle_web_fetch(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    return web_fetch(args["url"], host_url=ctx.config.platform_host_url)


def _ensure_platform_client(ctx: ToolContext) -> PlatformToolClient | None:
    if not ctx.config.platform_tools_enabled:
        return None
    if ctx.platform is None:
        ctx.platform = PlatformToolClient(ctx.config.platform_host_url)
    return ctx.platform


def _handle_platform(ctx: ToolContext, tool_name: str, args: dict[str, Any]) -> ToolResult:
    client = _ensure_platform_client(ctx)
    if client is None:
        return ToolResult.failure(
            tool_name,
            "PLATFORM_DISABLED",
            "Set AGENT_PLATFORM_TOOLS=1 to enable platform tools",
        )
    payload = dict(args)
    payload.pop("payload", None)
    return client.invoke(tool_name, ctx.run_id, payload)


def _ensure_browser_client(ctx: ToolContext) -> BrowserToolClient | None:
    if not ctx.config.browser_enabled:
        return None
    if ctx.browser is None:
        ctx.browser = BrowserToolClient(ctx.config.browser_url)
    return ctx.browser


def _handle_browser(ctx: ToolContext, tool_name: str, args: dict[str, Any]) -> ToolResult:
    client = _ensure_browser_client(ctx)
    if client is None:
        return ToolResult.failure(tool_name, "BROWSER_DISABLED", "Browser tools are disabled for this agent run")
    return client.invoke(tool_name, ctx.run_id, args)


def _make_browser_handler(tool_name: str) -> Handler:
    def _handler(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
        return _handle_browser(ctx, tool_name, args)

    return _handler


HANDLERS: dict[str, Handler] = {
    "read_file": _handle_read_file,
    "write_file": _handle_write_file,
    "str_replace": _handle_str_replace,
    "delete_file": _handle_delete_file,
    "glob": _handle_glob,
    "grep": _handle_grep,
    "run_terminal": _handle_run_terminal,
    "read_lints": _handle_read_lints,
    "todo_write": _handle_todo_write,
    "web_fetch": _handle_web_fetch,
}

for _name in sorted(BROWSER_TOOLS):
    HANDLERS[_name] = _make_browser_handler(_name)

for _pname in sorted(PLATFORM_TOOL_NAMES):
    HANDLERS[_pname] = (lambda n: lambda ctx, args: _handle_platform(ctx, n, args))(_pname)


def is_read_only_tool(name: str) -> bool:
    return name in READ_ONLY_TOOLS


def execute_tool(ctx: ToolContext, name: str, arguments: dict[str, Any]) -> ToolResult:
    handler = HANDLERS.get(name)
    if handler is None:
        return ToolResult.failure(name, "unknown_tool", f"Unknown tool: {name}")
    try:
        return handler(ctx, arguments)
    except KeyError as exc:
        return ToolResult.failure(name, "missing_argument", f"Missing required argument: {exc.args[0]}")
    except Exception as exc:  # pragma: no cover - safety net
        return ToolResult.failure(name, "internal_error", str(exc))


def parse_tool_arguments(raw: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    return json.loads(raw)
