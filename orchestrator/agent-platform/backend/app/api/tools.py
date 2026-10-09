from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.tools.invoke import ToolCallResult, invoke_tool
from app.tools.registry import get_tool, list_groups, list_tools

router = APIRouter()


class ToolInvokeBody(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    agent_id: str | None = None


class NamedToolInvokeBody(ToolInvokeBody):
    tool: str


@router.get("/tools")
def get_tools() -> dict[str, object]:
    return {"items": [item.model_dump() for item in list_tools()]}


@router.get("/tools/groups")
def get_tool_groups() -> dict[str, object]:
    tools = list_tools()
    return {
        "items": [
            {
                **group.model_dump(),
                "tool_count": sum(1 for tool in tools if tool.group == group.id),
                "available_count": sum(
                    1 for tool in tools if tool.group == group.id and tool.available
                ),
            }
            for group in list_groups()
        ]
    }


# Имя в теле — тот же контракт, что POST /api/v1/tools/invoke у Constructor.
@router.post("/tools/invoke")
async def post_tool_invoke(body: NamedToolInvokeBody) -> ToolCallResult:
    return await _invoke(body.tool, body)


@router.get("/tools/{name}")
def get_tool_card(name: str) -> dict[str, object]:
    spec = get_tool(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"tool not found: {name}")
    return spec.model_dump()


@router.post("/tools/{name}/invoke")
async def post_named_tool_invoke(name: str, body: ToolInvokeBody) -> ToolCallResult:
    return await _invoke(name, body)


async def _invoke(name: str, body: ToolInvokeBody) -> ToolCallResult:
    if get_tool(name) is None:
        raise HTTPException(status_code=404, detail=f"tool not found: {name}")
    return await invoke_tool(name, body.arguments, agent_id=body.agent_id)
