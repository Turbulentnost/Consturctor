from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.core.jwt import AuthContext
from app.schemas.workflow import WebSearchRequest, WebSearchResponse, WebSearchResultItem

router = APIRouter(prefix="/tools", tags=["tools"])

_TOOLS_WEBSEARCH = (
    Path(__file__).resolve().parents[4] / "tools" / "web_search_tool"
)


def _ensure_websearch_path() -> None:
    path = str(_TOOLS_WEBSEARCH)
    if path not in sys.path:
        sys.path.insert(0, path)


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
