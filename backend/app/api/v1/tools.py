from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.config import settings
from app.services.agent_platform import list_allowed_tools_with_metadata
from app.core.jwt import AuthContext
from app.services import platform_proxy
from platform_contracts.tools import ToolInvokeRequest, ToolResult

router = APIRouter(prefix="/tools", tags=["tools"])


def _ensure_tool_allowed(tool_name: str, auth: AuthContext) -> None:
    allowed = settings.allowed_tools_for_department(auth.department)
    if allowed is not None and tool_name not in allowed:
        raise HTTPException(status_code=403, detail=f"Tool not allowed: {tool_name}")


@router.get("")
async def list_tools(auth: AuthContext = Depends(get_current_user)) -> dict:
    tools = list_allowed_tools_with_metadata(auth.department or "")
    return {"items": tools, "department": auth.department}


@router.post("/{tool_name}/invoke", response_model=ToolResult)
async def invoke_tool(
    tool_name: str,
    body: ToolInvokeRequest,
    auth: AuthContext = Depends(get_current_user),
) -> ToolResult:
    _ensure_tool_allowed(tool_name, auth)
    if not body.department:
        body = body.model_copy(update={"department": auth.department, "user_id": auth.user_id})
    authorization = f"Bearer internal"
    try:
        return await platform_proxy.invoke_tool(tool_name, body, authorization=authorization)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
