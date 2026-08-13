from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.local_mcp import LocalMcpError, call_tool, list_tools


AgentEventCallback = Callable[[dict[str, Any]], None]


class AgentRuntimeError(RuntimeError):
    pass


def available_tools() -> list[dict[str, Any]]:
    return list_tools()


def run_agent_task(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
    message: str,
    emit: AgentEventCallback,
) -> dict[str, Any]:
    workflow = (
        db.query(Workflow)
        .filter(Workflow.id == workflow_id, Workflow.user_id == user_id)
        .first()
    )
    if workflow is None:
        raise AgentRuntimeError("Workflow не найден")
    task = message.strip()
    if not task:
        raise AgentRuntimeError("Пустая задача")

    emit({"type": "thinking", "text": "Получил задачу и сверяю её с готовым workflow.\n"})
    emit({"type": "agent_message", "text": f"Запускаю агента «{workflow.title or 'ИИ-агент'}»."})

    tool_result: dict[str, Any] | None = None
    if _needs_web_search(task):
        arguments = {"query": task, "max_results": 5, "fetch_top": False}
        emit({"type": "tool_call", "tool": "web_search", "arguments": arguments})
        try:
            tool_result = call_tool("web_search", arguments)
        except LocalMcpError as exc:
            emit({"type": "error", "message": str(exc)})
            raise AgentRuntimeError(str(exc)) from exc
        emit({"type": "tool_result", "tool": "web_search", "result": tool_result})

    answer = _compose_answer(task, tool_result)
    emit({"type": "agent_message", "text": answer})
    return {"answer": answer, "tool_result": tool_result or {}}


def _needs_web_search(text: str) -> bool:
    lowered = text.casefold()
    return any(word in lowered for word in ("найди", "поиск", "интернет", "сайт", "сведения", "актуальн"))


def _compose_answer(task: str, tool_result: dict[str, Any] | None) -> str:
    if not tool_result:
        return (
            "Задача принята. Для выполнения без внешнего поиска использую сформированный workflow "
            f"и переданные материалы: {task}"
        )
    results = tool_result.get("results") or []
    if not results:
        return "Я выполнил web_search, но подходящих результатов не нашёл."
    lines = ["Я выполнил поиск через локальный MCP-инструмент и нашёл:"]
    for item in results[:3]:
        title = str(item.get("title") or "Без названия")
        url = str(item.get("url") or "")
        snippet = str(item.get("snippet") or "")
        lines.append(f"- {title}: {snippet} {url}".strip())
    return "\n".join(lines)
