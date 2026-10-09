"""Ответ runner на tool_request: исполнить инструмент из каталога и вернуть tool_result."""

from __future__ import annotations

from app.sdk.protocol import ToolRequestEvent, ToolResultCommand
from app.tools.invoke import invoke_tool


async def answer_tool_request(
    event: ToolRequestEvent, *, agent_id: str | None = None
) -> ToolResultCommand:
    call = await invoke_tool(event.tool, event.arguments, agent_id=agent_id)
    result = call.result if isinstance(call.result, dict) else {"result": call.result}
    return ToolResultCommand(
        request_id=event.request_id,
        ok=call.ok,
        result=result if call.ok else {},
        error=call.error or "",
    )
