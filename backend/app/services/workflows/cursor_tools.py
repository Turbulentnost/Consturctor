"""Cursor Cloud Agent ↔ desktop tools during workflow creation."""

from __future__ import annotations

import json
import logging
import re
from contextvars import ContextVar
from typing import Any, Callable

from app.clients import cursor as cursor_client
from app.services.local_mcp import list_tools
from app.services.tool_bridge import DEFAULT_TIMEOUT_S, tool_bridge

logger = logging.getLogger(__name__)

WorkflowEmit = Callable[..., None]

_tool_ctx: ContextVar[tuple[str, str] | None] = ContextVar("creation_tool_ctx", default=None)

_TOOL_BLOCK_RE = re.compile(
    r"```(?:constructor_tool|tool)\s*\n(\{.*?\})\s*```",
    re.DOTALL,
)
_MAX_ROUNDS_PLAN = 6
_MAX_ROUNDS_EXECUTE = 10
_MAX_CALLS_PER_ROUND = 3
_MAX_TOOL_FAILURES = 2
_MAX_NUDGES = 2


def set_tool_context(run_id: str, user_id: str) -> None:
    _tool_ctx.set((run_id, user_id))


def clear_tool_context() -> None:
    _tool_ctx.set(None)


def current_tool_context() -> tuple[str, str] | None:
    return _tool_ctx.get()


def tools_prompt_block() -> str:
    lines = [
        "Реестр Constructor. ```constructor_tool — markdown в ответе, не tool Cursor. "
        "Backend перехватывает блок и вызывает tool на сервере. "
        "Не пиши «нет доступа к constructor_tool».",
        "Первый ответ — ТОЛЬКО один блок (без плана и кода вокруг):",
        "```constructor_tool",
        '{"name": "turboproject", "arguments": {}}',
        "```",
        "Не вызывай BACKEND_URL, curl и HTTP с Cloud VM. Не выдумывай результат. "
        "Дождись ответа системы и только потом продолжи.",
        "Когда Constructor tool уже ответил — верни финальный ответ (JSON плана или RESULT) "
        "без блока constructor_tool.",
        "Каталог:",
    ]
    for item in list_tools():
        name = str(item.get("name") or "")
        if not name:
            continue
        desc = str(item.get("description") or "").replace("\n", " ")
        schema = item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {}
        props = list((schema.get("properties") or {}).keys())
        required = list(schema.get("required") or [])
        exec_at = str(item.get("execution") or "desktop")
        extra = f" args={props}" if props else ""
        if required:
            extra += f" required={required}"
        lines.append(f"- {name} [{exec_at}]: {desc}{extra}")
    return "\n".join(lines)


def with_tools_if_desktop(prompt: str) -> str:
    if current_tool_context() is None:
        return prompt
    return prompt.rstrip() + "\n\n" + tools_prompt_block() + "\n"


def extract_tool_calls(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in _TOOL_BLOCK_RE.finditer(text or ""):
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("name") or data.get("tool") or "").strip()
        if not name:
            continue
        arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
        calls.append({"name": name, "arguments": arguments})
    return calls


def should_run_tool_calls(text: str, *, mode: str) -> list[dict[str, Any]]:
    calls = extract_tool_calls(text)
    if not calls:
        return []
    if mode == "plan":
        from app.services.workflows.prompts import parse_plan_from_text

        plan = parse_plan_from_text(text)
        if plan.title.strip() and plan.steps:
            return []
        return calls
    # execute: не глушить цикл из-за TESTS: FAIL — в тексте ещё может быть constructor_tool
    return calls


def tool_family(name: str) -> str:
    raw = (name or "").strip().casefold()
    if not raw:
        return ""
    return raw.split(".", 1)[0]


_LIVE_FAMILIES = frozenset({"turboproject", "onec", "imap", "outlook"})


def required_live_tools_from_plan(plan: Any) -> list[str]:
    """Families from plan (runtime.kind / steps / answers), not hardcoded field lists."""
    parts: list[str] = [
        str(getattr(plan, "title", "") or ""),
        str(getattr(plan, "goal", "") or ""),
        str(getattr(getattr(plan, "runtime", None), "kind", "") or ""),
        str(getattr(plan, "raw_text", "") or ""),
    ]
    for step in getattr(plan, "steps", None) or []:
        parts.extend(
            [
                str(getattr(step, "title", "") or ""),
                str(getattr(step, "action", "") or ""),
                str(getattr(step, "done_when", "") or ""),
            ]
        )
    for group in (
        getattr(plan, "answered_questions", None) or [],
        getattr(plan, "open_questions", None) or [],
    ):
        for item in group:
            parts.extend(
                [
                    str(getattr(item, "question", "") or ""),
                    str(getattr(item, "answer", "") or ""),
                    str(getattr(item, "why", "") or ""),
                ]
            )
    for bucket in (
        getattr(plan, "constraints", None) or [],
        getattr(plan, "test_criteria", None) or [],
    ):
        parts.extend(str(x) for x in bucket)
    blob = " ".join(parts).casefold()
    families: list[str] = []

    def add(family: str) -> None:
        key = (family or "").strip().casefold()
        if key in _LIVE_FAMILIES and key not in families:
            families.append(key)

    kind = str(getattr(getattr(plan, "runtime", None), "kind", "") or "").casefold()
    if "turbo" in kind or "turboproject" in blob or "ms project" in blob:
        add("turboproject")
    if kind == "onec" or any(tip in blob for tip in ("onec.", "1с", "odata", "erp_pm")):
        add("onec")
    if "imap" in kind or any(tip in blob for tip in ("imap.", "imap ")):
        add("imap")
    if kind == "outlook_calendar" or any(
        tip in blob for tip in ("календар", "совещан", "outlook.application", "win32com")
    ):
        add("outlook")
    return families


def _covers_required(required: str, successful: set[str]) -> bool:
    req = (required or "").casefold()
    return any(item == req or item.startswith(req) for item in successful)


def invoke_creation_tool(
    *,
    tool: str,
    arguments: dict[str, Any],
    on_event: WorkflowEmit | None,
    workflow_id: str = "",
) -> dict[str, Any]:
    from app.services.agent_runtime import (
        _IMAP_TOOLS,
        _ONEC_TOOLS,
        _invoke_imap_server,
        _invoke_onec_server,
    )

    args = dict(arguments or {})
    if workflow_id:
        args.setdefault("workflow_id", workflow_id)
        args.setdefault("agent_id", workflow_id)
    if tool.startswith("imap.") or tool in _IMAP_TOOLS:
        return _invoke_imap_server(tool, args)
    if tool in _ONEC_TOOLS:
        ctx = current_tool_context()
        user_id = ctx[1] if ctx else ""
        return _invoke_onec_server(tool, args, user_id=user_id)
    if tool in {"turboproject", "turboproject.projects"} or tool.startswith("turboproject"):
        from app.services.agent_runtime import _invoke_turboproject_server

        return _invoke_turboproject_server(tool, args)

    ctx = current_tool_context()
    if ctx is None:
        raise RuntimeError("Нет desktop-сессии для вызова инструмента")
    run_id, user_id = ctx
    request_id = tool_bridge.new_request_id()
    tool_bridge.begin_wait(request_id=request_id, user_id=user_id)
    _emit(
        on_event,
        "tool_request",
        f"Выполняю на компьютере: {tool}…",
        {
            "run_id": run_id,
            "request_id": request_id,
            "tool": tool,
            "arguments": args,
        },
    )
    payload = tool_bridge.await_result(request_id=request_id, timeout_s=DEFAULT_TIMEOUT_S)
    if not payload.get("ok"):
        raise RuntimeError(str(payload.get("error") or f"Ошибка инструмента {tool}"))
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


def stream_cursor_with_tools(
    *,
    agent_id: str,
    run_id: str,
    on_event: WorkflowEmit | None,
    workflow_id: str = "",
    mode: str = "plan",
    stream_run,
    required_live_tools: list[str] | None = None,
) -> Any:
    """Stream a Cursor run; if it asks for constructor_tool, execute and continue."""
    last = stream_run(agent_id, run_id, on_event=on_event)
    if current_tool_context() is None:
        return _attach_live_ok(last, set())
    required = [tool_family(name) for name in (required_live_tools or []) if tool_family(name)]
    successful: set[str] = set()
    fail_counts: dict[str, int] = {}
    unreachable: set[str] = set()
    last_errors: dict[str, str] = {}
    nudge_without_call = 0
    max_rounds = _MAX_ROUNDS_EXECUTE if mode == "execute" else _MAX_ROUNDS_PLAN

    def missing_required() -> list[str]:
        return [
            name
            for name in required
            if not _covers_required(name, successful) and name not in unreachable
        ]

    for _round_n in range(max_rounds):
        calls = should_run_tool_calls(getattr(last, "text", None) or "", mode=mode)
        if not calls and mode == "execute":
            pending = missing_required()
            if pending and nudge_without_call < _MAX_NUDGES:
                nudge_without_call += 1
                _emit(
                    on_event,
                    "decision",
                    "Жду вызов Constructor tool: " + ", ".join(pending),
                )
                follow = _nudge_live_tools_prompt(pending)
                run = cursor_client.create_run(agent_id, prompt=follow, mode="agent")
                next_id = str(run.get("id") or "")
                if not next_id:
                    return _attach_live_ok(last, successful)
                last = stream_run(agent_id, next_id, on_event=on_event)
                continue
            return _attach_live_ok(last, successful)
        if not calls:
            return _attach_live_ok(last, successful)

        nudge_without_call = 0
        results: list[dict[str, Any]] = []
        for call in calls[:_MAX_CALLS_PER_ROUND]:
            name = str(call.get("name") or "")
            family = tool_family(name)
            _emit(on_event, "decision", f"Cursor вызывает «{name}»…")
            if name.startswith("turboproject") or name == "turboproject":
                _emit(
                    on_event,
                    "decision",
                    "«turboproject»: читаю проекты на сервере Constructor "
                    "(это может занять до минуты)…",
                )
            try:
                result = invoke_creation_tool(
                    tool=name,
                    arguments=call.get("arguments") or {},
                    on_event=on_event,
                    workflow_id=workflow_id,
                )
                results.append({"name": name, "ok": True, "result": _clip_result(result)})
                if family:
                    successful.add(family)
                    fail_counts[family] = 0
                    unreachable.discard(family)
                _emit(on_event, "decision", f"«{name}»: готово.")
            except Exception as exc:  # noqa: BLE001
                logger.warning("Creation tool %s failed: %s", name, exc)
                results.append({"name": name, "ok": False, "error": str(exc)})
                if family:
                    fail_counts[family] = fail_counts.get(family, 0) + 1
                    last_errors[family] = str(exc)
                    if fail_counts[family] >= _MAX_TOOL_FAILURES:
                        unreachable.add(family)
                _emit(on_event, "decision", f"«{name}»: {exc}")
        pending = missing_required()
        follow = _followup_prompt(
            results,
            mode=mode,
            pending=pending,
            unreachable=sorted(unreachable),
            last_errors=last_errors,
        )
        run = cursor_client.create_run(agent_id, prompt=follow, mode="agent")
        next_id = str(run.get("id") or "")
        if not next_id:
            return _attach_live_ok(last, successful)
        last = stream_run(agent_id, next_id, on_event=on_event)
    return _attach_live_ok(last, successful)


def _attach_live_ok(last: Any, successful: set[str]) -> Any:
    names = sorted(successful)
    if last is not None and hasattr(last, "successful_live_tools"):
        last.successful_live_tools = names
    return last


def _nudge_live_tools_prompt(pending: list[str]) -> str:
    names = ", ".join(pending)
    return (
        "Ты ещё не получил ответ Constructor tool для: "
        f"{names}.\n"
        "Не используй BACKEND_URL, curl и HTTP с Cloud VM — на VM их нет, это не FAIL.\n"
        "Верни ТОЛЬКО один блок ```constructor_tool с name из каталога Constructor "
        f"(сейчас нужен {names}). Дождись фактов от backend, не останавливайся."
    )


def _followup_prompt(
    results: list[dict[str, Any]],
    *,
    mode: str,
    pending: list[str] | None = None,
    unreachable: list[str] | None = None,
    last_errors: dict[str, str] | None = None,
) -> str:
    blob = json.dumps(results, ensure_ascii=False, indent=2, default=str)
    if mode == "plan":
        tail = (
            "Учти результаты инструментов. "
            "Если нужно ещё проверить — снова верни только ```constructor_tool. "
            "Иначе верни финальный JSON плана по схеме, без блока constructor_tool."
        )
    elif pending:
        tail = (
            "Это факты Constructor, не Cloud VM. "
            "Ещё нет успешного ответа для: "
            f"{', '.join(pending)}. "
            "Снова верни только ```constructor_tool. "
            "Не пиши TESTS: FAIL из-за BACKEND_URL / Cloud VM."
        )
    elif unreachable:
        errors = last_errors or {}
        detail = "; ".join(f"{name}: {errors.get(name) or 'ошибка'}" for name in unreachable)
        tail = (
            "Constructor tool повторно вернул ошибку. "
            f"Цель недостижима: {detail}. "
            "Запиши это в RESULT.md и TESTS: FAIL. Не вини Cloud VM / BACKEND_URL."
        )
    else:
        tail = (
            "Учти результаты Constructor tools и продолжи реализацию. "
            "Если данных достаточно — RESULT.md с предметным выводом и TESTS: PASS. "
            "Если нужен ещё вызов — только ```constructor_tool. "
            "Не ставь FAIL из-за отсутствия BACKEND_URL на Cloud VM."
        )
    return (
        "Результаты вызовов инструментов Constructor (факты с сервера/desktop, не с VM):\n"
        f"{blob}\n\n{tail}"
    )


def _clip_result(result: dict[str, Any], limit: int = 8000) -> dict[str, Any]:
    try:
        raw = json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return {"text": str(result)[:limit]}
    if len(raw) <= limit:
        return result
    return {"truncated": True, "preview": raw[:limit] + "…"}


def _emit(
    on_event: WorkflowEmit | None,
    event_type: str,
    text: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    if on_event is None:
        return
    if extra:
        try:
            on_event(event_type, text, extra)
            return
        except TypeError:
            pass
    if text:
        on_event(event_type, text)
