"""Инструменты Constructor (NewConstructor/desktop/app/tools, перенесены в app/vendors/constructor)."""

from __future__ import annotations

import inspect
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.tools.constructor_session import ensure_session
from app.tools.providers import ImplementedTool, relative_source
from app.tools.registry import Invoker

_FIXED_SOURCES = {
    "web_search": "app/vendors/constructor/tools/web_search_tool",
    "site_browser": "app/vendors/constructor/tools/site_browser_tool",
    "plan_export": "app/vendors/constructor/tools/roseltorg_tender_search",
    "onec.meeting_protocols": "app/vendors/constructor/tools/meeting_protocols_local.py",
    "onec.meeting_service_notes": "app/vendors/constructor/tools/meeting_memo_queue.py",
    "onec.search_documents": "app/vendors/constructor/tools/onec_documents_odata_local.py",
    "onec.get_document_card": "app/vendors/constructor/tools/onec_documents_odata_local.py",
}
_SERVER_SOURCE = "app/vendors/constructor/tools/server_tools.py"


def _invoker(name: str) -> Invoker:
    async def invoke(arguments: dict[str, Any]) -> Any:
        from app.vendors.constructor.tools.host import invoke_tool

        await run_in_threadpool(ensure_session)
        return await run_in_threadpool(invoke_tool, name, arguments)

    return invoke


def discover() -> list[ImplementedTool]:
    from app.vendors.constructor.tools.ac.dispatch import get_registry
    from app.vendors.constructor.tools.catalog import list_desktop_tools
    from app.vendors.constructor.tools.server_tools import (
        LOCAL_BACKEND_TOOL_NAMES,
        SERVER_TOOL_NAMES,
    )

    registry = get_registry()
    tools: list[ImplementedTool] = []
    for item in list_desktop_tools():
        name = str(item["name"])
        # Маршрут как в host.invoke_tool: серверные имена уходят на backend даже при локальной регистрации.
        server = name in SERVER_TOOL_NAMES and name not in LOCAL_BACKEND_TOOL_NAMES
        tool = ImplementedTool(
            name=name,
            project="NewConstructor",
            description=str(item.get("description") or ""),
            input_schema=dict(item.get("inputSchema") or {"type": "object", "properties": {}}),
            execution="server" if server else "local",
            source_path=_SERVER_SOURCE if server else _FIXED_SOURCES.get(name, ""),
            invoker=_invoker(name),
            timeout_seconds=item.get("timeoutSeconds"),
            runtime=str(item.get("runtime") or ""),
        )
        if registry.has_tool(name):
            implementation = registry.get(name)
            definition = implementation.definition
            tool.title = definition.title
            tool.side_effect = definition.side_effect_level.value
            tool.requires_approval = definition.requires_human_approval
            if not tool.source_path:
                tool.source_path = relative_source(inspect.getsourcefile(type(implementation)))
        tools.append(tool)
    return tools
