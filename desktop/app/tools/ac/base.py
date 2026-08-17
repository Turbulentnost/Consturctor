"""Базовый интерфейс инструмента агента."""

from abc import ABC, abstractmethod

from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
)


class BaseTool(ABC):
    """Базовый интерфейс инструмента.

    Инструмент не должен сам решать, можно ли его вызвать. Он только выполняет
    действие, если будущий ToolGateway уже разрешил вызов.
    """

    definition: ToolDefinition

    def __init__(self, definition: ToolDefinition) -> None:
        """Сохранить паспорт инструмента."""
        self.definition = definition

    @abstractmethod
    def execute(self, input_data: dict) -> ToolCallResult:
        """Выполнить конкретный инструмент с уже проверенными входными данными."""
