"""Инструменты уведомлений и справочника пользователей."""

from __future__ import annotations

from app.tools.ported.ac.base import BaseTool
from app.tools.ported.ac.registry import ToolRegistry
from app.tools.ported.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.runtime_api import request


class UsersListTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="users.list",
                title="Список пользователей",
                description=(
                    "Возвращает пользователей Constructor: id, ФИО, должность, подразделение. "
                    "Нужен, чтобы выбрать получателя для notify.send."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=30,
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Поиск по ФИО, должности или id"},
                    },
                },
                output_schema={
                    "type": "object",
                    "properties": {"users": {"type": "array"}},
                },
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        query = str(input_data.get("query") or input_data.get("search") or "").strip()
        try:
            data = request("GET", "/api/v1/notifications/users", params={"search": query} if query else None)
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="USERS_LIST_FAILED",
                error_message=str(exc),
            )
        items = data.get("items") if isinstance(data, dict) else []
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={"users": items if isinstance(items, list) else []},
        )


class NotifySendTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="notify.send",
                title="Отправить уведомление",
                description=(
                    "Отправляет уведомление пользователю Constructor. "
                    "Параметр user_id — кому, send_at — когда (ISO, пусто = сразу). "
                    "Чтобы узнать id, ФИО и должность получателя, сначала вызови инструмент users.list."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                input_schema={
                    "type": "object",
                    "properties": {
                        "user_id": {
                            "type": "string",
                            "description": "id получателя из users.list",
                        },
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "send_at": {"type": "string"},
                        "workflow_id": {"type": "string"},
                    },
                    "required": ["user_id", "title"],
                },
                output_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        user_id = str(input_data.get("user_id") or input_data.get("recipient_user_id") or "").strip()
        title = str(input_data.get("title") or "").strip()
        if not user_id or not title:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_INPUT",
                error_message="Нужны user_id и title.",
            )
        workflow_id = str(
            input_data.get("workflow_id")
            or (input_data.get("runtime_context") or {}).get("workflow_id")
            or input_data.get("agent_id")
            or ""
        ).strip()
        send_at = str(input_data.get("send_at") or "").strip() or None
        payload = {
            "recipient_user_id": user_id,
            "title": title,
            "body": str(input_data.get("body") or ""),
            "workflow_id": workflow_id,
        }
        if send_at:
            payload["send_at"] = send_at
        try:
            data = request("POST", "/api/v1/notifications", json=payload)
        except Exception as exc:  # noqa: BLE001
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="NOTIFY_SEND_FAILED",
                error_message=str(exc),
            )
        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data=data if isinstance(data, dict) else {"ok": True},
        )


def register_notify_tools(registry: ToolRegistry, *, skip_existing: bool = False) -> None:
    for tool in (UsersListTool(), NotifySendTool()):
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)
