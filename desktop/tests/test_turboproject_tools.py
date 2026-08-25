from app.tools.ac.registry import ToolRegistry
from app.tools.ac.turboproject_tools import (
    GET_BLOCKED_TASKS_TOOL_NAME,
    GET_OVERDUE_PROJECTS_TOOL_NAME,
    GET_PORTFOLIO_SUMMARY_TOOL_NAME,
    GET_PROJECT_METRICS_TOOL_NAME,
    GET_PROJECT_TASKS_TOOL_NAME,
    GET_PROJECT_TOOL_NAME,
    GET_WORKLOAD_SUMMARY_TOOL_NAME,
    SEARCH_PROJECTS_TOOL_NAME,
    register_turboproject_tools,
)


def test_desktop_catalog_contains_new_turboproject_tools() -> None:
    registry = ToolRegistry()

    register_turboproject_tools(registry)

    names = registry.list_tool_names()
    assert {
        SEARCH_PROJECTS_TOOL_NAME,
        GET_PROJECT_TOOL_NAME,
        GET_PROJECT_TASKS_TOOL_NAME,
        GET_PROJECT_METRICS_TOOL_NAME,
        GET_OVERDUE_PROJECTS_TOOL_NAME,
        GET_BLOCKED_TASKS_TOOL_NAME,
        GET_WORKLOAD_SUMMARY_TOOL_NAME,
        GET_PORTFOLIO_SUMMARY_TOOL_NAME,
    } <= names
    overdue_tool = registry.get(GET_OVERDUE_PROJECTS_TOOL_NAME)
    assert "просрочены" in overdue_tool.definition.description.casefold()
    tasks_tool = registry.get(GET_PROJECT_TASKS_TOOL_NAME)
    assert "project_id" in tasks_tool.definition.input_schema.get("required", [])
