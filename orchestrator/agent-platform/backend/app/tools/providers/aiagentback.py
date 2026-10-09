"""Инструменты AIAgentBack (AIAgents/AIAgentBack/app/tools, перенесены в app/vendors/aiagentback)."""

from __future__ import annotations

import importlib
import inspect
import logging
from typing import Any

from fastapi.encoders import jsonable_encoder

from app.tools.providers import ImplementedTool, relative_source
from app.tools.registry import Invoker

logger = logging.getLogger(__name__)

# Обёртки регистрируют инструменты в tool_registry при импорте.
_WRAPPERS = ("system_tools", "fs_tools", "outlook_tools", "onec_tools")
_RUNTIME_BY_WRAPPER = {"outlook_tools": "ews", "onec_tools": "odata", "fs_tools": "fs"}
_SCHEMA_MAPS = ("properties", "$defs", "definitions", "patternProperties")


def clean_schema(node: Any, in_map: bool = False) -> Any:
    """Убрать из JSON Schema pydantic служебный шум: title, default=None, anyOf с null."""
    if isinstance(node, list):
        return [clean_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    if in_map:
        return {key: clean_schema(value) for key, value in node.items()}
    variants = node.get("anyOf")
    if isinstance(variants, list):
        rest = [item for item in variants if item != {"type": "null"}]
        if len(rest) == 1 and len(rest) < len(variants):
            merged = {key: value for key, value in node.items() if key != "anyOf"}
            node = {**rest[0], **merged}
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        if key == "default" and value is None:
            continue
        cleaned[key] = clean_schema(value, in_map=key in _SCHEMA_MAPS)
    return cleaned


def _invoker(tool: Any) -> Invoker:
    async def invoke(arguments: dict[str, Any]) -> Any:
        from app.vendors.aiagentback.tools.schemas import ToolContext

        params = dict(arguments)
        agent_id = params.pop("agent_id", None)
        payload = tool.input_model.model_validate(params) if tool.input_model else None
        context = ToolContext.model_construct(
            db=None, user=None, agent_id=agent_id, task_id=None, allow_open_web=False
        )
        return jsonable_encoder(await tool.execute(payload, context))

    return invoke


def discover() -> list[ImplementedTool]:
    from app.vendors.aiagentback.tools.registry import tool_registry

    wrapper_by_tool: dict[str, str] = {}
    for wrapper in _WRAPPERS:
        before = {tool.name for tool in tool_registry.list()}
        try:
            importlib.import_module(f"app.vendors.aiagentback.tools.{wrapper}")
        except Exception:  # noqa: BLE001
            logger.exception("AIAgentBack tools %s are unavailable", wrapper)
            continue
        for tool in tool_registry.list():
            if tool.name not in before:
                wrapper_by_tool[tool.name] = wrapper

    tools: list[ImplementedTool] = []
    for tool in tool_registry.list():
        if not tool.implemented:
            continue
        schema = tool.input_schema or {"type": "object", "properties": {}}
        tools.append(
            ImplementedTool(
                name=tool.name,
                project="AIAgentBack",
                description=tool.agent_description or tool.description,
                input_schema=clean_schema(schema),
                execution="local",
                source_path=relative_source(inspect.getsourcefile(type(tool))),
                invoker=_invoker(tool),
                title=tool.description,
                runtime=_RUNTIME_BY_WRAPPER.get(wrapper_by_tool.get(tool.name, ""), ""),
            )
        )
    return tools
