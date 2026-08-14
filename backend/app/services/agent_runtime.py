from __future__ import annotations

import re
from typing import Any, Callable
from urllib.parse import quote_plus

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.local_mcp import list_tools
from app.services.plan_run import (
    PlanRunError,
    build_plan_export_arguments,
    format_plan_run_answer,
    uses_plan_export,
)
from app.services.tool_bridge import DEFAULT_TIMEOUT_S, tool_bridge


AgentEventCallback = Callable[[dict[str, Any]], None]

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_ROSELTORG_SEARCH = "https://www.roseltorg.ru/procedures/search"

_ETP_HINTS = (
    "roseltorg",
    "росэлторг",
    "этп",
    "закуп",
    "тендер",
    "223-фз",
    "44-фз",
    "площадк",
)

_IMAP_TOOLS = frozenset(
    {
        "imap.list_unread",
        "imap.search",
        "imap.fetch_message",
        "imap.fetch_attachments",
    }
)


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
    run_id: str,
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

    emit({"type": "status", "text": "Получил задачу, готовлю запуск…"})
    emit({"type": "agent_message", "text": f"Запускаю «{workflow.title or 'ИИ-агент'}»."})

    # Rules come from THIS agent's plan (runtime / constraints / answers), not globals.
    if uses_plan_export(workflow):
        emit({"type": "status", "text": "Читаю правила из паспорта этого агента…"})
        emit(
            {
                "type": "agent_message",
                "text": (
                    "Выполняю по правилам из ответов при создании: поиск по ключам, "
                    "Excel с указанными колонками, сохранение куда указано в плане."
                ),
            }
        )
        try:
            arguments = build_plan_export_arguments(workflow)
        except PlanRunError as exc:
            emit({"type": "error", "message": str(exc)})
            raise AgentRuntimeError(str(exc)) from exc

        try:
            result = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                tool="plan_export",
                arguments=arguments,
            )
        except AgentRuntimeError as exc:
            emit({"type": "error", "message": str(exc)})
            raise

        answer = format_plan_run_answer(result)
        emit({"type": "tool_result", "tool": "plan_export", "result": result})
        emit({"type": "agent_message", "text": answer})
        return {"answer": answer, "tool": "plan_export", "tool_result": result}

    tool_name = ""
    tool_result: dict[str, Any] | None = None
    arguments: dict[str, Any] = {}

    browser_args = _site_browser_args(task, workflow)
    if browser_args:
        tool_name = "site_browser"
        arguments = browser_args
        emit({"type": "thinking", "text": "Открываю площадку и собираю закупки.\n"})
    else:
        query = _search_query(task, workflow)
        if query:
            tool_name = "web_search"
            arguments = {"query": query, "max_results": 8, "fetch_top": False}
            emit({"type": "thinking", "text": "Ищу информацию в интернете.\n"})

    if tool_name:
        try:
            tool_result = _request_desktop_tool(
                emit,
                run_id=run_id,
                user_id=user_id,
                tool=tool_name,
                arguments=arguments,
            )
        except AgentRuntimeError as exc:
            if tool_name == "site_browser":
                emit({"type": "thinking", "text": "Повторяю открытие площадки…\n"})
                retry = {
                    "action": "open",
                    "url": _ROSELTORG_SEARCH,
                    "wait_ms": 2500,
                    "max_items": 25,
                    "headless": True,
                }
                try:
                    tool_result = _request_desktop_tool(
                        emit,
                        run_id=run_id,
                        user_id=user_id,
                        tool="site_browser",
                        arguments=retry,
                    )
                    arguments = retry
                except AgentRuntimeError as exc2:
                    emit({"type": "error", "message": str(exc2)})
                    raise AgentRuntimeError(str(exc2)) from exc2
            else:
                emit({"type": "error", "message": str(exc)})
                raise
        emit({"type": "tool_result", "tool": tool_name, "result": tool_result})

    answer = _compose_answer(task, tool_name, tool_result)
    emit({"type": "agent_message", "text": answer})
    return {"answer": answer, "tool": tool_name, "tool_result": tool_result or {}}


def _request_desktop_tool(
    emit: AgentEventCallback,
    *,
    run_id: str,
    user_id: str,
    tool: str,
    arguments: dict[str, Any],
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    if tool.startswith("imap.") or tool in _IMAP_TOOLS:
        return _invoke_imap_server(tool, arguments)

    request_id = tool_bridge.new_request_id()
    tool_bridge.begin_wait(request_id=request_id, user_id=user_id)
    emit({"type": "tool_call", "tool": tool, "arguments": arguments})
    emit(
        {
            "type": "tool_request",
            "run_id": run_id,
            "request_id": request_id,
            "tool": tool,
            "arguments": arguments,
        }
    )
    try:
        payload = tool_bridge.await_result(
            request_id=request_id,
            timeout_s=timeout_s,
        )
    except TimeoutError as exc:
        raise AgentRuntimeError(str(exc)) from exc

    if not payload.get("ok"):
        raise AgentRuntimeError(str(payload.get("error") or f"Ошибка инструмента {tool}"))
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def _invoke_imap_server(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    _ = arguments
    # Server-side only; full IMAP microservice lands later.
    raise AgentRuntimeError(
        f"Инструмент {tool} выполняется на сервере и пока не подключён. "
        "Почтовые операции (IMAP) не уходят на desktop."
    )


def _is_etp_agent(task: str, workflow: Workflow) -> bool:
    blob = f"{task}\n{workflow.title or ''}\n{workflow.document_name or ''}".casefold()
    notes = ""
    try:
        notes = str(getattr(workflow, "notes", "") or "")
    except Exception:
        notes = ""
    blob = f"{blob}\n{notes.casefold()}"
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    constraints = "\n".join(str(c) for c in (plan.get("constraints") or []))
    blob = f"{blob}\n{constraints.casefold()}"
    return any(h in blob for h in _ETP_HINTS)


def _extract_url(text: str) -> str:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(").,;") if m else ""


def _keyword_from_task(task: str, workflow: Workflow) -> str:
    """Short search keyword; never the whole agent title sentence."""
    text = _URL_RE.sub("", task or "")
    for junk in (
        r"найди\s+актуальн\w*\s+закупки(?:\s+по\s+теме)?",
        r"открой\s+сайт\s+площадки",
        r"верни\s+список.*",
        r"с\s+названиями\s+и\s+ссылками",
        r"ии-агент\s*:",
        r"осуществляет\s+поиск\s+закупок\s+на\s+этп",
        r"поиск\s+закупок\s+на\s+\w+",
        r"на\s+этп",
    ):
        text = re.sub(junk, " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[«»\"']", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-:")
    for token in ("бумага", "лекарств", "медицин", "строитель", "мониторинг"):
        if token in (task or "").casefold():
            return token
    if not text or _is_etp_agent(text, workflow) or len(text.split()) <= 2:
        if _is_etp_agent(task, workflow):
            return ""
    words = [w for w in text.split() if len(w) > 3][:3]
    return " ".join(words)[:80] if words else ""


def _search_query(task: str, workflow: Workflow) -> str:
    kw = _keyword_from_task(task, workflow)
    return kw or (workflow.title or task)[:120]


def _site_browser_args(task: str, workflow: Workflow) -> dict[str, Any] | None:
    if not _is_etp_agent(task, workflow) and not _extract_url(task):
        return None

    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    plan_url = ""
    for c in plan.get("constraints") or []:
        plan_url = _extract_url(str(c))
        if plan_url:
            break
    url = _extract_url(task) or plan_url or _ROSELTORG_SEARCH
    keyword = _keyword_from_task(task, workflow)

    if "roseltorg" in url.casefold() or url == _ROSELTORG_SEARCH:
        base = url.split("?")[0] if "procedures/search" in url else _ROSELTORG_SEARCH
        if keyword:
            # Keep source filters from plan URL when present.
            if "?" in url and "search=" not in url.casefold():
                url = f"{url}&search={quote_plus(keyword)}"
            elif "?" in url:
                url = re.sub(r"([?&])search=[^&]*", rf"\1search={quote_plus(keyword)}", url)
            else:
                url = f"{base}?search={quote_plus(keyword)}"
        return {
            "action": "open",
            "url": url,
            "wait_ms": 2500,
            "max_items": 25,
            "headless": True,
        }

    return {
        "action": "open",
        "url": url,
        "wait_ms": 2000,
        "max_items": 25,
        "headless": True,
    }


def _compose_answer(task: str, tool_name: str, tool_result: dict[str, Any] | None) -> str:
    if not tool_result:
        return "Не удалось получить данные. Попробуйте ещё раз или уточните задачу."

    if tool_name == "site_browser":
        cards = tool_result.get("cards") or []
        lines = ["Нашла закупки на площадке:"]
        if cards:
            for item in cards[:10]:
                title = str(item.get("title") or "Без названия").strip()
                url = str(item.get("url") or "").strip()
                snippet = str(item.get("text") or "").strip()
                line = f"• {title}"
                if url:
                    line += f"\n  {url}"
                elif snippet:
                    line += f"\n  {snippet[:160]}"
                lines.append(line)
            return "\n".join(lines)
        text = str(tool_result.get("text") or "").strip()
        if text:
            return "Открыла страницу площадки, но список карточек пуст. Фрагмент страницы:\n" + text[:1200]
        return (
            "Не удалось прочитать список закупок с площадки. "
            "Проверьте доступ в интернет и попробуйте ещё раз."
        )

    results = tool_result.get("results") or []
    if not results:
        return (
            "Поиск в интернете не дал результатов. "
            "Для закупок лучше открывать площадку напрямую — нажмите «Запустить типовую задачу» ещё раз."
        )
    lines = ["Нашла в интернете:"]
    for item in results[:5]:
        title = str(item.get("title") or "Без названия")
        url = str(item.get("url") or "")
        lines.append(f"• {title}\n  {url}".rstrip())
    return "\n".join(lines)
