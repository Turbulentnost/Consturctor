from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.schemas.workflow import WebSearchRequest, WebSearchResponse, WebSearchResultItem
from app.services.imap_tools import ImapToolError, imap_configured, invoke_imap
from app.services.onec_artifacts import ArtifactError, load_artifact_file
from app.services.onec_tools import ONEC_TOOLS, OnecToolError, invoke_onec, odata_configured
from app.services.tool_names import resolve_tool_name
from app.services.turboproject import (
    TURBOPROJECT_TOOLS,
    TurboProjectError,
    invoke_turboproject,
    turboproject_configured,
)

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

_TURBOPROJECT_TOOLS = TURBOPROJECT_TOOLS
_USERS_TOOLS = frozenset(
    {
        "users.current",
        "users.subordinates",
        "users.list",
        "notify.send",
    }
)
_SERVER_TOOLS = _IMAP_TOOLS | ONEC_TOOLS | _TURBOPROJECT_TOOLS | _USERS_TOOLS


class ToolInvokeBody(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool: str = ""


_INLINE_INVOKE_BASE64_CHARS = 350_000


def _reject_unknown_tool(tool_name: str) -> None:
    raise HTTPException(
        status_code=400,
        detail=(
            f"Инструмент «{tool_name}» через этот endpoint только для "
            "imap.* / onec.* / turboproject. Desktop-tools идут через agent-runs SSE."
        ),
    )


def _artifact_invoke_view(result: dict[str, Any]) -> dict[str, Any]:
    out = dict(result)
    file_id = str(out.get("file_id") or "").strip()
    if file_id:
        out["content_url"] = f"/api/v1/tools/onec-artifacts/{file_id}"
    raw = out.get("content_base64")
    if isinstance(raw, str) and len(raw) > _INLINE_INVOKE_BASE64_CHARS:
        out.pop("content_base64", None)
        out["content_omitted"] = True
    return out


def _dispatch_server_tool(
    tool_name: str,
    arguments: dict[str, Any],
    auth: AuthContext,
) -> dict[str, Any]:
    resolved = resolve_tool_name(tool_name, _SERVER_TOOLS)
    if resolved is None:
        _reject_unknown_tool(tool_name)
        return {}
    tool_name = resolved
    try:
        if tool_name in _IMAP_TOOLS:
            result = invoke_imap(tool_name, arguments)
        elif tool_name in _TURBOPROJECT_TOOLS:
            result = invoke_turboproject(tool_name, arguments)
        elif tool_name in _USERS_TOOLS:
            result = _invoke_users_tool(tool_name, arguments, auth)
        else:
            result = invoke_onec(
                tool_name,
                arguments,
                actor_user_id=auth.user_id,
                actor_fio=auth.fio or "",
            )
    except (ImapToolError, OnecToolError, TurboProjectError, ArtifactError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if tool_name == "onec.download_artifact" and isinstance(result, dict):
        result = _artifact_invoke_view(result)
    return {"ok": True, "tool": tool_name, "result": result}


def _ensure_websearch_path() -> None:
    path = str(_TOOLS_WEBSEARCH)
    if path not in sys.path:
        sys.path.insert(0, path)


@router.get("/imap/status")
async def imap_status(auth: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    _ = auth
    return {
        "configured": imap_configured(),
        "mode": "real" if imap_configured() else "stub",
        "tools": sorted(_IMAP_TOOLS),
    }


@router.get("/turboproject/status")
async def turboproject_status(auth: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    _ = auth
    return {
        "configured": turboproject_configured(),
        "mode": "real" if turboproject_configured() else "stub",
        "tools": sorted(_TURBOPROJECT_TOOLS),
    }


@router.get("/onec/status")
async def onec_status(auth: AuthContext = Depends(get_current_user)) -> dict[str, Any]:
    _ = auth
    return {
        "configured": odata_configured(),
        "mode": "real" if odata_configured() else "stub",
        "tools": sorted(ONEC_TOOLS),
    }


@router.post("/invoke")
async def invoke_named_tool(
    body: ToolInvokeBody,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    name = str(body.tool or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="tool is required")
    return _dispatch_server_tool(name, body.arguments, auth)


@router.get("/onec-artifacts/{file_id}")
async def download_onec_artifact(
    file_id: str,
    auth: AuthContext = Depends(get_current_user),
) -> Response:
    _ = auth
    try:
        artifact = load_artifact_file(file_id)
    except ArtifactError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    safe_name = Path(artifact.filename).name.encode("ascii", "replace").decode("ascii")
    headers = {
        "Content-Disposition": f'attachment; filename="{safe_name}"',
        "X-Constructor-Filename": safe_name,
        "X-Constructor-File-Id": artifact.file_id,
    }
    return Response(
        content=artifact.content,
        media_type=artifact.content_type or "application/octet-stream",
        headers=headers,
    )


@router.post("/{tool_name}/invoke")
async def invoke_tool(
    tool_name: str,
    body: ToolInvokeBody,
    auth: AuthContext = Depends(get_current_user),
) -> dict[str, Any]:
    return _dispatch_server_tool(tool_name, body.arguments, auth)


def _invoke_users_tool(
    tool_name: str,
    arguments: dict[str, Any],
    auth: AuthContext,
) -> dict[str, Any]:
    """Serverside users.* / notify.send for the desktop SDK agent proxy.

    Sets tool context from the JWT session so users.current / notify.send
    resolve the caller without an active SSE run.
    """
    from app.services.workflows.cursor_tools import (
        _invoke_notify_send,
        _invoke_users_current,
        _invoke_users_list,
        _invoke_users_subordinates,
        clear_tool_context,
        set_tool_context,
    )

    set_tool_context(run_id="", user_id=auth.user_id)
    try:
        if tool_name == "users.current":
            return _invoke_users_current()
        if tool_name == "users.subordinates":
            return _invoke_users_subordinates(arguments)
        if tool_name == "users.list":
            return _invoke_users_list(arguments)
        return _invoke_notify_send(arguments)
    finally:
        clear_tool_context()


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
