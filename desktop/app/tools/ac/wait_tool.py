"""Инструмент паузы агента: отложить работу на заданное число секунд.

Используется, когда агенту нужно подождать перед следующим действием: пока
придёт письмо с кодом, загрузится страница, истечёт задержка перед повтором
или снимется ограничение по частоте запросов. Пауза кооперативная: сон идёт
маленькими шагами и прерывается, если пользователь остановил агента.
"""

from __future__ import annotations

import time
from typing import Callable

from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry

WAIT_TOOL_NAME = "agent.wait"
MAX_WAIT_SECONDS = 3600.0
_SLEEP_STEP_SECONDS = 0.25


class AgentWaitTool(BaseTool):
    """Приостанавливает работу агента на указанное число секунд."""

    def __init__(self) -> None:
        """Создать инструмент паузы."""
        super().__init__(
            ToolDefinition(
                name=WAIT_TOOL_NAME,
                title="Пауза агента",
                description=(
                    "Откладывает работу агента на заданное число секунд. "
                    "Полезно, когда нужно подождать: пока придёт письмо/код, "
                    "загрузится страница, истечёт задержка перед повторной "
                    "попыткой или снимется ограничение по частоте запросов."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.LOCAL,
                requires_human_approval=False,
                timeout_seconds=int(MAX_WAIT_SECONDS) + 60,
                input_schema={
                    "type": "object",
                    "properties": {
                        "seconds": {
                            "type": "number",
                            "minimum": 0,
                            "description": "На сколько секунд отложить работу",
                        }
                    },
                    "required": ["seconds"],
                },
                output_schema={
                    "type": "object",
                    "properties": {
                        "requested_seconds": {"type": "number"},
                        "waited_seconds": {"type": "number"},
                        "capped": {"type": "boolean"},
                        "cancelled": {"type": "boolean"},
                    },
                },
            )
        )
        # Runtime может подставить проверку отмены, чтобы пауза прерывалась при
        # остановке агента пользователем. По умолчанию отмены нет.
        self.cancel_check: Callable[[], bool] | None = None

    def execute(self, input_data: dict) -> ToolCallResult:
        """Поспать заданное число секунд (кооперативно, с учётом отмены)."""
        raw_seconds = input_data.get("seconds")
        try:
            seconds = float(raw_seconds)
        except (TypeError, ValueError):
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_SECONDS",
                error_message="Параметр seconds должен быть числом секунд.",
            )
        if seconds < 0:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="INVALID_SECONDS",
                error_message="seconds не может быть отрицательным.",
            )

        capped_seconds = min(seconds, MAX_WAIT_SECONDS)
        waited = 0.0
        cancelled = False
        while waited < capped_seconds:
            if self.cancel_check is not None and self.cancel_check():
                cancelled = True
                break
            step = min(_SLEEP_STEP_SECONDS, capped_seconds - waited)
            time.sleep(step)
            waited += step

        return ToolCallResult(
            ok=True,
            tool_name=self.definition.name,
            output_data={
                "requested_seconds": seconds,
                "waited_seconds": round(waited, 3),
                "capped": seconds > MAX_WAIT_SECONDS,
                "cancelled": cancelled,
            },
        )


def register_wait_tool(
    registry: ToolRegistry,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать инструмент паузы в реестре."""
    tool = AgentWaitTool()
    if skip_existing and registry.has_tool(tool.definition.name):
        return
    registry.register(tool)
