"""Build the ported tool registry and execute a named desktop tool."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.tools.ac.agent_workspace import AgentWorkspaceResolver
from app.tools.ac.code_execution_tools import register_code_execution_tools
from app.tools.ac.document_tools import register_document_tools
from app.tools.ac.com_backed_tools import (
    OutlookCreateEventComTool,
    OutlookReadCalendarComTool,
    OutlookSearchMailComTool,
)
from app.tools.ac.excel_tools import register_excel_tools
from app.tools.ac.onec_tools import register_onec_readonly_tools
from app.tools.ac.powershell_tools import register_powershell_tools
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.report_tools import register_report_tools
from app.tools.ac.notify_tools import register_notify_tools
from app.tools.ac.calendar_tools import register_calendar_tools
from app.tools.ac.schedule_tools import register_schedule_tools
from app.tools.ac.turboproject_tools import register_turboproject_tools
from app.tools.ac.wait_tool import register_wait_tool
from app.tools.ac.web_tools import register_web_tools
from app.tools.ac.workers import com_availability
from app.tools.ac.workers.onec_worker import OneCReadOnlyWorker
from app.tools.ac.workers.outlook_com_worker import OutlookComWorker
from app.tools.ac.workers.subprocess_com_worker import SubprocessComWorker


class AcToolError(RuntimeError):
    pass


def _workspaces_root() -> Path:
    local = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local) / "Constructor" / "agent_workspaces"


def workspaces_root() -> Path:
    return _workspaces_root()


def _ensure_agent_id(arguments: dict[str, Any]) -> dict[str, Any]:
    payload = dict(arguments)
    if not payload.get("agent_id") and payload.get("workflow_id"):
        payload["agent_id"] = str(payload["workflow_id"])
    context = payload.get("runtime_context")
    if not isinstance(context, dict):
        context = {}
    if not context.get("agent_id"):
        context["agent_id"] = str(
            payload.get("agent_id") or payload.get("workflow_id") or "default"
        )
    payload["runtime_context"] = context
    return payload


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    resolver = AgentWorkspaceResolver(_workspaces_root())
    outlook_read = SubprocessComWorker()
    # Запись в календарь — в процессе GUI: subprocess Outlook отклоняет Save («Не выполнено»).
    outlook_write = OutlookComWorker(safe_mode=True, allow_direct_com_calls=True)
    registry.register(OutlookSearchMailComTool(outlook_read))
    registry.register(OutlookReadCalendarComTool(outlook_read))
    registry.register(OutlookCreateEventComTool(outlook_write))
    register_onec_readonly_tools(registry, _onec_com_worker())
    register_report_tools(registry, skip_existing=True)
    register_document_tools(registry, resolver, skip_existing=True)
    register_web_tools(registry, skip_existing=True, workspace_resolver=resolver)
    register_excel_tools(registry, resolver, skip_existing=True)
    register_powershell_tools(registry, resolver, skip_existing=True)
    register_code_execution_tools(registry, resolver, skip_existing=True)
    register_wait_tool(registry, skip_existing=True)
    register_notify_tools(registry, skip_existing=True)
    register_schedule_tools(registry, skip_existing=True)
    register_calendar_tools(registry, skip_existing=True)
    register_turboproject_tools(registry, skip_existing=True)
    return registry


_REGISTRY: ToolRegistry | None = None


def _onec_com_worker():
    """1С COM: 32-bit V83.COMConnector через cscript, не py -3.12-32."""
    if com_availability.is_onec_com_available():
        return SubprocessComWorker()
    return OneCReadOnlyWorker()


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry()
    return _REGISTRY


def invoke_ac_tool(name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    args = _ensure_agent_id(arguments if isinstance(arguments, dict) else {})
    registry = get_registry()
    if not registry.has_tool(name):
        raise AcToolError(f"Неизвестный инструмент: {name}")
    result = registry.get(name).execute(args)
    if result.ok:
        return result.output_data if isinstance(result.output_data, dict) else {}
    message = result.error_message or result.error_type or f"Ошибка инструмента {name}"
    raise AcToolError(str(message))
