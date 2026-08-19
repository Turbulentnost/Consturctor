"""MCP stdio: все desktop-инструменты Constructor для агента Cursor."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_message() -> dict | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        decoded = line.decode("utf-8", errors="replace")
        if ":" not in decoded:
            continue
        key, value = decoded.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length") or 0)
    if length <= 0:
        return None
    body = sys.stdin.buffer.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(payload: dict) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(data)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def _ok(request_id, result: dict) -> None:
    _write_message({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id, message: str, code: int = -32000) -> None:
    _write_message(
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }
    )


def _call_tool(name: str, arguments: dict) -> dict:
    from app.tools import ToolHostError, invoke_tool
    from app.tools.hitl import confirm_level1_tool, needs_confirmation

    if (
        name.startswith("imap.")
        or name.startswith("onec.odata")
        or name.startswith("onec.erp_tasks")
        or name == "onec.erp_subordinate_tasks"
        or name == "onec.docflow_tasks"
        or name == "onec.sql_query"
    ):
        raise ToolHostError(
            f"«{name}» выполняется на backend Constructor, не в MCP-процессе Cursor."
        )
    if needs_confirmation(name) and not confirm_level1_tool(name, arguments):
        raise ToolHostError(
            "Запись и прочие операции уровня 1 требуют подтверждения в окне Constructor."
        )
    return invoke_tool(name, arguments)


def main() -> int:
    from app.tools.catalog import list_desktop_tools

    tools = list_desktop_tools()
    while True:
        message = _read_message()
        if message is None:
            return 0
        method = str(message.get("method") or "")
        request_id = message.get("id")
        params = message.get("params") if isinstance(message.get("params"), dict) else {}
        if method == "initialize":
            _ok(
                request_id,
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "constructor-desktop", "version": "1.0.0"},
                },
            )
            continue
        if method == "notifications/initialized" or method.startswith("notifications/"):
            continue
        if method == "tools/list":
            _ok(request_id, {"tools": tools})
            continue
        if method == "tools/call":
            name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            try:
                result = _call_tool(name, arguments)
                text = json.dumps(result, ensure_ascii=False, default=str)
                _ok(
                    request_id,
                    {
                        "content": [{"type": "text", "text": text}],
                        "isError": False,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                traceback.print_exc(file=sys.stderr)
                _ok(
                    request_id,
                    {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    },
                )
            continue
        if method == "ping":
            _ok(request_id, {})
            continue
        if request_id is not None:
            _error(request_id, f"Unknown method: {method}", code=-32601)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
