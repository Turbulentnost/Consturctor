"""Local tool host: executes agent tools on the user's machine."""

from __future__ import annotations

import base64
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

from app.config import DESKTOP_ROOT, REPO_ROOT


class ToolHostError(RuntimeError):
    pass


def _tools_root() -> Path:
    candidates = [
        REPO_ROOT / "tools",
        DESKTOP_ROOT / "tools",
        DESKTOP_ROOT.parent / "tools",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return REPO_ROOT / "tools"


def _ensure_path(subdir: str) -> Path:
    root = _tools_root() / subdir
    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)
    return root


def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}

    # Server-executed tools (1C OData/SQL, IMAP, users, notify) are proxied to the
    # Constructor backend. Everything else runs on this desktop by default, so no
    # locally written tool can leak to the server.
    from app.tools.server_tools import SERVER_TOOL_NAMES, canonical_server_tool_name

    name = canonical_server_tool_name(name)
    if name in SERVER_TOOL_NAMES:
        return _invoke_server_tool(name, args)
    if name == "data.process":
        raise ToolHostError(
            "Инструмент data.process доступен только в серверном прогоне, не на desktop."
        )

    handler = _HANDLERS.get(name)
    if handler is not None:
        return handler(args)
    from app.tools.ac.dispatch import AcToolError, invoke_ac_tool

    try:
        return invoke_ac_tool(name, args)
    except AcToolError as exc:
        raise ToolHostError(str(exc)) from exc


def _server_tool_timeout(name: str) -> float:
    from app.tools.server_tools import server_tool_timeout_seconds

    extra = server_tool_timeout_seconds(name)
    return float(extra) if extra > 0 else 180.0


def _invoke_server_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Proxy a server-executed tool to the Constructor backend.

    Prefers POST /api/v1/tools/invoke with the tool name in the JSON body so
    dotted names like onec.download_artifact are not lost in the URL path.
    """
    from app.tools import runtime_api

    timeout = _server_tool_timeout(name)
    try:
        data = runtime_api.request(
            "POST",
            "/api/v1/tools/invoke",
            json={"tool": name, "arguments": args},
            timeout=timeout,
        )
    except RuntimeError as exc:
        raise ToolHostError(str(exc)) from exc
    if isinstance(data, dict) and "result" in data:
        result = data.get("result")
        payload = result if isinstance(result, dict) else {"result": result}
        return _materialize_downloaded_artifact(payload)
    payload = data if isinstance(data, dict) else {"result": data}
    return _materialize_downloaded_artifact(payload) if isinstance(data, dict) else payload


def _write_artifact_bytes(name: str, content: bytes, result: dict[str, Any]) -> dict[str, Any]:
    dest_dir = Path(tempfile.gettempdir()) / "constructor-onec-artifacts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(name).name
    dest.write_bytes(content)
    out = dict(result)
    out.pop("content_base64", None)
    out["file"] = str(dest)
    out["path"] = str(dest)
    out["result_file"] = str(dest)
    out["filename"] = dest.name
    return out


def _fetch_artifact_bytes(result: dict[str, Any]) -> bytes | None:
    from app.tools import runtime_api

    url = str(result.get("content_url") or "").strip()
    file_id = str(result.get("file_id") or "").strip()
    path = url if url.startswith("/") else ""
    if not path and file_id:
        path = f"/api/v1/tools/onec-artifacts/{file_id}"
    if not path:
        return None
    try:
        return runtime_api.request_bytes("GET", path, timeout=300.0)
    except Exception:  # noqa: BLE001
        return None


def _materialize_downloaded_artifact(result: dict[str, Any]) -> dict[str, Any]:
    raw = result.get("content_base64")
    name = str(result.get("filename") or "").strip()
    content: bytes | None = None
    if raw and name:
        try:
            content = base64.b64decode(str(raw), validate=True)
        except Exception:
            content = None
    if content is None:
        content = _fetch_artifact_bytes(result)
        if not name:
            name = str(result.get("filename") or "artifact.bin").strip() or "artifact.bin"
    if not content or not name:
        return result
    return _write_artifact_bytes(name, content, result)


def _web_search(arguments: dict[str, Any]) -> dict[str, Any]:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolHostError("Пустой query")
    _ensure_path("web_search_tool")
    try:
        from websearch.engine import search, search_and_extract  # type: ignore
    except ImportError as exc:
        raise ToolHostError(f"web_search_tool не найден: {exc}") from exc

    max_results = int(arguments.get("max_results") or 5)
    fetch_top = bool(arguments.get("fetch_top"))
    try:
        if fetch_top:
            payload = search_and_extract(query, max_results=max_results)
            raw_results = list(payload.get("results") or [])
            extracted = str(payload.get("text") or payload.get("extracted_text") or "")
            engine = str(payload.get("engine") or "")
        else:
            raw_results, engine = search(query, max_results=max_results)
            extracted = ""
    except Exception as exc:  # noqa: BLE001
        raise ToolHostError(f"Ошибка web_search: {exc}") from exc

    results: list[dict[str, str]] = []
    for item in raw_results:
        if hasattr(item, "title"):
            results.append(
                {
                    "title": str(item.title or ""),
                    "url": str(item.url or ""),
                    "snippet": str(getattr(item, "snippet", "") or ""),
                }
            )
        elif isinstance(item, dict):
            results.append(
                {
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "snippet": str(item.get("snippet") or ""),
                }
            )
    return {
        "query": query,
        "engine": engine,
        "results": results,
        "extracted_text": extracted or "",
    }


def _site_browser(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    if not url:
        raise ToolHostError("Пустой url")
    _ensure_path("site_browser_tool")
    try:
        from sitebrowser.browser import SiteBrowserError, browse  # type: ignore
    except ImportError as exc:
        raise ToolHostError(
            f"site_browser_tool не найден: {exc}. "
            "Установите: pip install -r tools/site_browser_tool/requirements.txt "
            "&& python -m playwright install chromium"
        ) from exc

    action = str(arguments.get("action") or "open").strip().lower() or "open"
    try:
        return browse(
            action=action,
            url=url,
            query=str(arguments.get("query") or ""),
            headless=True,
            wait_ms=int(arguments.get("wait_ms") or 0),
            wait_selector=str(arguments.get("wait_selector") or "") or None,
            input_selector=str(arguments.get("input_selector") or "") or None,
            submit_selector=str(arguments.get("submit_selector") or "") or None,
            item_selector=str(arguments.get("item_selector") or "") or None,
            title_selector=str(arguments.get("title_selector") or "") or None,
            link_selector=str(arguments.get("link_selector") or "") or None,
            max_items=int(arguments.get("max_items") or 30),
        )
    except SiteBrowserError as exc:
        raise ToolHostError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ToolHostError(f"Ошибка site_browser: {exc}") from exc
_HANDLERS: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "web_search": _web_search,
    "site_browser": _site_browser,
}
