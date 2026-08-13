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
    query = _search_query(task, workflow)
    if query:
        fetch_top = _needs_page_extract(task)
        arguments = {"query": query, "max_results": 8, "fetch_top": fetch_top}
        emit(
            {
                "type": "thinking",
                "text": (
                    "Целевой сайт ЭТП из cloud VM может быть недоступен — "
                    "использую локальный web_search (DuckDuckGo/Wikipedia).\n"
                ),
            }
        )
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


_SEARCH_HINTS = (
    "найди",
    "поиск",
    "интернет",
    "сайт",
    "сведения",
    "актуальн",
    "закуп",
    "тендер",
    "roseltorg",
    "росэлторг",
    "этп",
    "мониторинг",
    "оферт",
    "live",
    "прогон",
)


def _needs_web_search(text: str) -> bool:
    lowered = text.casefold()
    return any(word in lowered for word in _SEARCH_HINTS)


def _needs_page_extract(text: str) -> bool:
    lowered = text.casefold()
    return any(word in lowered for word in ("закуп", "тендер", "roseltorg", "росэлторг", "этп"))


def _search_query(task: str, workflow: Workflow) -> str:
    if not _needs_web_search(task) and not _needs_web_search(workflow.title or ""):
        # For published tender agents still search when task looks operational.
        lowered = task.casefold()
        if not any(w in lowered for w in ("запуск", "найди", "покажи", "проверь", "live")):
            return ""
    title = (workflow.title or "").strip()
    if _needs_web_search(task):
        return task
    if title:
        return f"{task} {title}".strip()
    return task


def _compose_answer(task: str, tool_result: dict[str, Any] | None) -> str:
    if not tool_result:
        return (
            "Задача принята. Для выполнения без внешнего поиска использую сформированный workflow "
            f"и переданные материалы: {task}"
        )
    results = tool_result.get("results") or []
    extracted = str(tool_result.get("extracted_text") or "").strip()
    if not results and not extracted:
        return "Я выполнил web_search, но подходящих результатов не нашёл."
    lines = ["Я выполнил поиск через локальный MCP-инструмент web_search и нашёл:"]
    for item in results[:5]:
        title = str(item.get("title") or "Без названия")
        url = str(item.get("url") or "")
        snippet = str(item.get("snippet") or "")
        lines.append(f"- {title}: {snippet} {url}".strip())
    if extracted:
        lines.append("")
        lines.append("Фрагмент страницы:")
        lines.append(extracted[:1200])
    return "\n".join(lines)
