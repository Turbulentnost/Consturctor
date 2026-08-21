"""Outlook + 1C COM tools and OData docflow."""

from __future__ import annotations

from typing import Any

from app.tools.docflow_tools import DocflowTasksTool
from app.tools.ported.ac.com_backed_tools import (
    OutlookCreateEventComTool,
    OutlookReadCalendarComTool,
    OutlookSearchMailComTool,
)
from app.tools.ported.ac.onec_tools import register_onec_readonly_tools
from app.tools.ported.ac.registry import ToolRegistry
from app.tools.ported.ac.tooling import ToolDefinition
from app.tools.ported.ac.workers import com_availability
from app.tools.ported.ac.workers.onec_worker import OneCReadOnlyWorker
from app.tools.ported.ac.workers.outlook_com_worker import OutlookComWorker
from app.tools.ported.ac.workers.subprocess_com_worker import SubprocessComWorker

COM_WORKER_MODULE = "app.tools.ported.ac.workers.com_worker_process"


class ToolError(RuntimeError):
    pass


def _onec_worker() -> SubprocessComWorker | OneCReadOnlyWorker:
    if com_availability.is_onec_com_available():
        return SubprocessComWorker(module_name=COM_WORKER_MODULE)
    return OneCReadOnlyWorker()


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    outlook_read = SubprocessComWorker(module_name=COM_WORKER_MODULE)
    outlook_write = OutlookComWorker(safe_mode=True, allow_direct_com_calls=True)
    registry.register(OutlookSearchMailComTool(outlook_read))
    registry.register(OutlookReadCalendarComTool(outlook_read))
    registry.register(OutlookCreateEventComTool(outlook_write))
    register_onec_readonly_tools(registry, _onec_worker())
    registry.register(DocflowTasksTool())
    return registry


_REGISTRY: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY


def list_tool_definitions() -> list[ToolDefinition]:
    return get_registry().list_tools()


def invoke_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    from app.tools.porucheniya_route import reroute_if_porucheniya

    args = dict(arguments or {})
    name, args = reroute_if_porucheniya(name, args)
    registry = get_registry()
    if not registry.has_tool(name):
        raise ToolError(f"Неизвестный инструмент: {name}")
    result = registry.get(name).execute(args)
    if result.ok:
        return result.output_data if isinstance(result.output_data, dict) else {"value": result.output_data}
    message = result.error_message or result.error_type or f"Ошибка {name}"
    raise ToolError(str(message))
