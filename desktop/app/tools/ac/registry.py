"""Каталог доступных инструментов приложения."""

from app.tools.ac.tooling import ToolDefinition
from app.tools.ac.base import BaseTool


class ToolRegistry:
    """Реестр инструментов без исполнения и без проверки прав AgentSpec."""

    def __init__(self) -> None:
        """Создать пустой реестр инструментов."""
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Зарегистрировать инструмент в реестре."""
        if not isinstance(tool, BaseTool):
            raise TypeError("tool должен быть экземпляром BaseTool")

        tool_name = tool.definition.name
        if not tool_name.strip():
            raise ValueError("tool.definition.name не должен быть пустым")

        if tool_name in self._tools:
            raise ValueError(f"Инструмент {tool_name!r} уже зарегистрирован")

        self._tools[tool_name] = tool

    def get(self, tool_name: str) -> BaseTool:
        """Вернуть инструмент по имени или выбросить понятную ошибку."""
        if tool_name not in self._tools:
            raise KeyError(f"Инструмент {tool_name!r} не найден в ToolRegistry")
        return self._tools[tool_name]

    def has_tool(self, tool_name: str) -> bool:
        """Проверить, зарегистрирован ли инструмент."""
        return tool_name in self._tools

    def list_tools(self) -> list[ToolDefinition]:
        """Вернуть паспорта всех зарегистрированных инструментов."""
        return [tool.definition for tool in self._tools.values()]

    def list_tool_names(self) -> set[str]:
        """Вернуть имена всех зарегистрированных инструментов."""
        return set(self._tools)
