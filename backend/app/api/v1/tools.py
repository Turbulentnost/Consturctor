from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.config import settings
from app.core.jwt import AuthContext
from app.schemas.workflow import WebSearchRequest, WebSearchResponse, WebSearchResultItem
from app.services.agent_platform import list_allowed_tools_with_metadata
from app.services import platform_proxy
from platform_contracts.tools import ToolInvokeRequest, ToolResult

router = APIRouter(prefix="/tools", tags=["tools"])

_TOOLS_WEBSEARCH = (
    Path(__file__).resolve().parents[4] / "tools" / "web_search_tool"
)


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
