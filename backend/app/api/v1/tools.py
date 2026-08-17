from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.schemas.workflow import WebSearchRequest, WebSearchResponse, WebSearchResultItem
from app.services.agent_platform import list_allowed_tools_with_metadata
from app.services.imap_tools import ImapToolError, imap_configured, invoke_imap
from app.services.onec_tools import ONEC_TOOLS, OnecToolError, invoke_onec, odata_configured
from app.services import platform_proxy
from platform_contracts.tools import ToolInvokeRequest, ToolResult

router = APIRouter(prefix="/tools", tags=["tools"])

_TOOLS_WEBSEARCH = (
    Path(__file__).resolve().parents[4] / "tools" / "web_search_tool"
)

_IMAP_TOOLS = frozenset(
    {
        "imap.list_unread",
        "imap.search",
        "imap.fetch_message",
        "imap.fetch_attachments",
    }
)

_SERVER_TOOLS = _IMAP_TOOLS | ONEC_TOOLS


class ToolInvokeBody(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def _ensure_websearch_path() -> None:
    path = str(_TOOLS_WEBSEARCH)
    if path not in sys.path:
        sys.path.insert(0, path)


def _ensure_tool_allowed(tool_name: str, auth: AuthContext) -> None:
    allowed = settings.allowed_tools_for_department(auth.department)
    if allowed is not None and tool_name not in allowed:
        raise HTTPException(status_code=403, detail=f"Tool not allowed: {tool_name}")


@router.get("")
async def list_tools(auth: AuthContext = Depends(get_current_user)) -> dict:
    tools = list_allowed_tools_with_metadata(auth.department or "")
    return {"items": tools, "department": auth.department}


@router.get("/imap/status")
async def imap_status(auth: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    _ = auth
    return {
        "configured": imap_configured(),
        "mode": "real" if imap_configured() else "stub",
        "tools": sorted(_IMAP_TOOLS),
    }


@router.get("/onec/status")
async def onec_status(auth: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    _ = auth
    return {
        "configured": odata_configured(),
        "mode": "real" if odata_configured() else "stub",
        "tools": sorted(ONEC_TOOLS),
    }


@router.post("/{tool_name}/invoke", response_model=ToolResult)
async def invoke_tool(
    tool_name: str,
    body: ToolInvokeRequest,
    auth: AuthContext = Depends(get_current_user),
) -> ToolResult:
    _ensure_tool_allowed(tool_name, auth)
    if not body.department:
        body = body.model_copy(update={"department": auth.department, "user_id": auth.user_id})
    authorization = "Bearer internal"
    try:
        return await platform_proxy.invoke_tool(tool_name, body, authorization=authorization)
    except platform_proxy.PlatformProxyError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.post("/{tool_name}/invoke-server")
async def invoke_server_tool(
    tool_name: str,
    body: ToolInvokeBody,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    if tool_name not in _SERVER_TOOLS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Инструмент «{tool_name}» через этот endpoint только для "
                "imap.* / onec.*. Platform-tools идут через /tools/{name}/invoke."
            ),
        )
    try:
        if tool_name in _IMAP_TOOLS:
            result = invoke_imap(tool_name, body.arguments)
        else:
            result = invoke_onec(
                tool_name,
                body.arguments,
                actor_user_id=auth.user_id,
                actor_fio=auth.fio or "",
            )
    except (ImapToolError, OnecToolError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "tool": tool_name, "result": result}


@router.post("/web-search", response_model=WebSearchResponse)
async def web_search(
    request: WebSearchRequest,
    auth: AuthContext = Depends(get_current_user),
) -> WebSearchResponse:
    _ = auth
    query = (request.query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Пустой query")
    _ensure_websearch_path()
    try:
        from websearch.engine import search, search_and_extract  # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"web_search_tool не найден ({_TOOLS_WEBSEARCH}): {exc}",
        ) from exc

    try:
        if request.fetch_top:
            results, text = search_and_extract(query, max_results=request.max_results)
            extracted = text or ""
        else:
            results = search(query, max_results=request.max_results)
            extracted = ""
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Ошибка веб-поиска: {exc}") from exc

    return WebSearchResponse(
        query=query,
        results=[
            WebSearchResultItem(title=r.title, url=r.url, snippet=r.snippet) for r in results
        ],
        extracted_text=extracted,
    )
