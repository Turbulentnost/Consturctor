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
_datasets: ContextVar["DatasetRegistry | None"] = ContextVar("creation_datasets", default=None)

_TOOL_BLOCK_RE = re.compile(
    r"```(?:constructor_tool|tool)\s*\n(\{.*?\})\s*```",
    re.DOTALL,
)
_MAX_ROUNDS_PLAN = 6
_MAX_ROUNDS_EXECUTE = 10
_MAX_CALLS_PER_ROUND = 3
_MAX_TOOL_FAILURES = 2
_MAX_NUDGES = 2

_GENERIC_USER_QUERIES = (
    "все",
    "всех",
    "получатель",
    "получатели",
    "пользователь",
    "пользователи",
    "сотрудник",
    "сотрудники",
    "человек",
    "люди",
    "адресат",
    "адресаты",
    "список",
    "users",
    "user",
    "кто",
    "кому",
    "директор",
    "руководител",
)


def set_tool_context(run_id: str, user_id: str) -> None:
    _tool_ctx.set((run_id, user_id))


def clear_tool_context() -> None:
    _tool_ctx.set(None)


def current_tool_context() -> tuple[str, str] | None:
    return _tool_ctx.get()


class DatasetRegistry:
    """Полные ответы инструментов прогона: модели уходит preview, коду — весь набор."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}
        self._n = 0

    def put(self, payload: Any) -> str:
        self._n += 1
        dataset_id = f"d{self._n}"
        self._items[dataset_id] = payload
        return dataset_id

    def get(self, dataset_id: str) -> Any:
        return self._items.get((dataset_id or "").strip())

    def latest_id(self) -> str:
        return f"d{self._n}" if self._n else ""

    def pack(self, result: Any, limit: int = 8000) -> dict[str, Any]:
        dataset_id = self.put(result)
        shape = _result_shape(result)
        try:
            raw = json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            raw = str(result)
        if len(raw) <= limit:
            if isinstance(result, dict):
                return {**result, "dataset_id": dataset_id, "shape": shape}
            return {"dataset_id": dataset_id, "shape": shape, "value": result}
        return {
            "dataset_id": dataset_id,
            "truncated": True,
            "preview": raw[:limit] + "…",
            "shape": shape,
        }


def _result_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        counts = {
            str(key): len(item)
            for key, item in value.items()
            if isinstance(item, list)
        }
        return {"type": "object", "keys": [str(key) for key in list(value.keys())[:40]], "counts": counts}
    if isinstance(value, list):
        return {"type": "array", "length": len(value)}
    return {"type": type(value).__name__}


def _validation_rules_block() -> str:
    from app.services.workflows.prompts import _VALIDATION_RULES

    return _VALIDATION_RULES


def tool_catalog_block() -> str:
    """Полный каталог по контрактам — запасной блок, когда шагов ещё нет."""
    lines = ["Каталог по системам (system · entity · operation):"]
    by_system: dict[str, list[str]] = {}
    for item in list_tools():
        name = str(item.get("name") or "")
        if not name:
            continue
        desc = str(item.get("description") or "").replace("\n", " ")
        schema = item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {}
        props = list((schema.get("properties") or {}).keys())
        required = list(item.get("required_filters") or schema.get("required") or [])
        exec_at = str(item.get("execution") or "desktop")
        system = str(item.get("system") or "desktop")
        entity = str(item.get("entity") or "—")
        operation = str(item.get("operation") or "—")
        extra = f" args={props}" if props else ""
        if required:
            extra += f" required={required}"
        result_fields = list(item.get("result_fields") or [])
        if result_fields:
            extra += f" returns={result_fields}"
        pagination = str(item.get("pagination") or "none")
        if pagination != "none":
            extra += f" pagination={pagination}"
        by_system.setdefault(system, []).append(
            f"- {name} [{exec_at}] {system}·{entity}·{operation}: {desc}{extra}"
        )
    for system in sorted(by_system):
        lines.append(f"[{system}]")
        lines.extend(by_system[system])
    return "\n".join(lines)


def contract_vocabulary_block() -> str:
    """Измерения контрактов для проектировщика: без имён инструментов."""
    from app.services.local_mcp import contract_vocabulary

    vocab = contract_vocabulary()
    lines = [
        "СЛОВАРЬ КОНТРАКТОВ. Для шага бери system, entity и operation только отсюда.",
        "systems: " + ", ".join(vocab["systems"]),
        "operations: " + ", ".join(vocab["operations"]),
        "Допустимые сочетания (system · entity · operation → обязательные параметры → поля результата):",
    ]
    for item in vocab["combinations"]:
        required = ", ".join(item["required_params"]) or "—"
        fields = ", ".join(item["result_fields"]) or "—"
        entity = item["entity"] or "—"
        lines.append(
            f"- {item['system']} · {entity} · {item['operation']} → {required} → {fields}"
        )
    return "\n".join(lines)


_TRANSPORT_HINT = (
    "ВЫЗОВ ИНСТРУМЕНТА. Это markdown-блок в твоём ответе, backend выполнит его сам:\n"
    "```constructor_tool\n"
    '{"name": "имя_из_разрешённых", "step": "s1", "arguments": {}}\n'
    "```\n"
    "Не ходи в HTTP, curl и BACKEND_URL. Не придумывай результат: дождись ответа backend."
)


def design_tools_block() -> str:
    """Разрешённые на проектировании tools берём из контрактов, не из текста промпта."""
    from app.services.local_mcp import design_context_tools

    allowed = design_context_tools()
    if not allowed:
        return "На этапе проектирования инструменты не вызываются."
    lines = [
        "Доступные сейчас инструменты (только контекст, бизнес-данные не читаем):",
    ]
    for tool in allowed:
        name = str(tool.get("name") or "")
        entity = str(tool.get("entity") or "—")
        lines.append(
            f"- {name}: {tool.get('system')} · {entity} · {tool.get('operation')}"
        )
    lines.append("Другие инструменты сейчас отклоняются backend.")
    lines.append(_TRANSPORT_HINT)
    return "\n".join(lines)


def helper_tools_block() -> str:
    from app.services.local_mcp import helper_tools

    allowed = helper_tools()
    if not allowed:
        return ""
    lines = [
        "ВСПОМОГАТЕЛЬНЫЕ ИНСТРУМЕНТЫ. Их можно вызывать на любом шаге, даже если их нет в кандидатах.",
        "Если ответ усечён или нужна выборка — вызови helper constructor · dataset · execute с dataset_id.",
    ]
    for tool in allowed:
        name = str(tool.get("name") or "")
        entity = str(tool.get("entity") or "—")
        lines.append(
            f"- {name}: {tool.get('system')} · {entity} · {tool.get('operation')}"
        )
    return "\n".join(lines)


def step_candidates_block(draft: dict[str, Any] | None) -> str:
    """Исполнителю показываем только кандидатов его шагов, не весь каталог."""
    steps = [step for step in ((draft or {}).get("steps") or []) if isinstance(step, dict)]
    if not steps:
        return ""
    lines = ["РАЗРЕШЁННЫЕ ИНСТРУМЕНТЫ ПО ШАГАМ. Вне этого списка вызовы отклоняются."]
    for index, step in enumerate(steps, start=1):
        step_id = str(step.get("id") or f"s{index}")
        candidates = [str(item) for item in (step.get("tool_candidates") or [])]
        names = ", ".join(candidates) if candidates else "нет кандидатов"
        required = ", ".join(str(item) for item in (step.get("required_params") or []))
        tail = f" параметры: {required}." if required else ""
        lines.append(f"- {step_id}: {names}.{tail}")
    lines.append(_TRANSPORT_HINT)
    return "\n".join(lines)


def tools_prompt_block(
    *,
    phase: str = "execute",
    draft: dict[str, Any] | None = None,
) -> str:
    """Блок инструментов по фазе: проектирование видит контекст, прогон — кандидатов шага."""
    from app.services.local_mcp import DESIGN_PHASE

    if phase == DESIGN_PHASE:
        return design_tools_block()
    scoped = step_candidates_block(draft)
    helper = helper_tools_block()
    if scoped:
        return "\n".join([part for part in (scoped, helper, _validation_rules_block()) if part])
    return "\n".join(
        [part for part in (_TRANSPORT_HINT, helper, _validation_rules_block(), tool_catalog_block()) if part]
    )


def with_tools_if_desktop(
    prompt: str,
    *,
    phase: str = "execute",
    draft: dict[str, Any] | None = None,
) -> str:
    """Прикладываем только то, что разрешено фазе.

    Полный реестр в промпте заставлял модель рассуждать про транспорт вместо задачи,
    поэтому для прогона отдаём кандидатов шагов, а для проектирования — контекст.
    """
    block = tools_prompt_block(phase=phase, draft=draft)
    return prompt.rstrip() + "\n\n" + block + "\n"


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
        call = {"name": name, "arguments": arguments}
        step = str(data.get("step") or data.get("step_id") or "").strip()
        if step:
            call["step"] = step
        calls.append(call)
    return calls


def _should_pause_for_clarify(text: str) -> bool:
    from app.services.workflows.prompts import parse_clarify_from_text

    return bool(parse_clarify_from_text(text))


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


_LIVE_FAMILIES = frozenset({"turboproject", "onec", "imap", "outlook", "notify"})

_NOTIFY_HINTS = (
    "уведом",
    "notify",
    "прислать",
    "написать получател",
    "колокольчик",
    "тост",
)


def wants_notifications(*blobs: str) -> bool:
    text = " ".join(blobs).casefold().replace("ё", "е")
    return any(hint in text for hint in _NOTIFY_HINTS)


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
    if wants_notifications(blob):
        add("notify")
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
    if tool in {"users.current", "current_user"}:
        return _invoke_users_current()
    if tool in {"users.list", "users"}:
        return _invoke_users_list(args)
    if tool in {"notify.send", "notify"}:
        return _invoke_notify_send(args)
    if tool in {"data.process", "data.process_dataset"}:
        return _invoke_data_process(args)

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


class StepLedger:
    """Статус каждого шага черновика: успешный вызов — ещё не выполненный шаг."""

    def __init__(self, draft: dict[str, Any] | None) -> None:
        self.steps: list[dict[str, Any]] = [
            step for step in ((draft or {}).get("steps") or []) if isinstance(step, dict)
        ]
        self.entries: dict[str, dict[str, Any]] = {}
        for index, step in enumerate(self.steps, start=1):
            step_id = str(step.get("id") or f"s{index}")
            self.entries[step_id] = {
                "id": step_id,
                "title": str(step.get("title") or ""),
                "required": bool(step.get("required", True)),
                "status": "pending",
                "data_status": "",
                "tool": "",
                "attempts": 0,
                "error": "",
                "reasons": [],
            }

    @property
    def enabled(self) -> bool:
        return bool(self.steps)

    def step_by_id(self, step_id: str) -> dict[str, Any] | None:
        for step in self.steps:
            if str(step.get("id") or "") == step_id:
                return step
        return None

    def next_step(self, step_id: str) -> dict[str, Any] | None:
        for index, step in enumerate(self.steps):
            if str(step.get("id") or "") == step_id:
                return self.steps[index + 1] if index + 1 < len(self.steps) else None
        return None

    def resolve(self, call: dict[str, Any]) -> dict[str, Any] | None:
        """Шаг из блока вызова, иначе — первый незакрытый шаг с таким инструментом."""
        declared = str(call.get("step") or "").strip()
        if declared:
            found = self.step_by_id(declared)
            if found is not None:
                return found
        name = str(call.get("name") or "")
        for step in self.steps:
            entry = self.entries.get(str(step.get("id") or ""), {})
            if entry.get("status") == "completed":
                continue
            if name in (step.get("tool_candidates") or []):
                return step
        return None

    def record(
        self,
        *,
        step: dict[str, Any] | None,
        name: str,
        verdict: Any,
        error: str = "",
    ) -> None:
        if step is None:
            return
        entry = self.entries.get(str(step.get("id") or ""))
        if entry is None:
            return
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
        entry["tool"] = name
        entry["error"] = error
        if error:
            entry["status"] = "failed"
            entry["data_status"] = "mismatch"
            entry["reasons"] = [error[:300]]
            return
        entry["data_status"] = verdict.data_status
        entry["reasons"] = list(verdict.reasons)
        entry["status"] = "completed" if verdict.accepted else "failed"

    def missing_required(self) -> list[str]:
        return [
            entry["id"]
            for entry in self.entries.values()
            if entry.get("required") and entry.get("status") != "completed"
        ]

    def as_list(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self.entries.values()]


def stream_cursor_with_tools(
    *,
    agent_id: str,
    run_id: str,
    on_event: WorkflowEmit | None,
    workflow_id: str = "",
    mode: str = "plan",
    stream_run,
    required_live_tools: list[str] | None = None,
    assumption_check: bool = False,
    draft: dict[str, Any] | None = None,
    phase: str = "execute",
) -> Any:
    """Stream a Cursor run; if it asks for constructor_tool, execute and continue."""
    registry = DatasetRegistry()
    datasets_token = _datasets.set(registry)
    try:
        return _stream_cursor_with_tools_body(
            agent_id=agent_id,
            run_id=run_id,
            on_event=on_event,
            workflow_id=workflow_id,
            mode=mode,
            stream_run=stream_run,
            required_live_tools=required_live_tools,
            assumption_check=assumption_check,
            draft=draft,
            phase=phase,
        )
    finally:
        _datasets.reset(datasets_token)


def _stream_cursor_with_tools_body(
    *,
    agent_id: str,
    run_id: str,
    on_event: WorkflowEmit | None,
    workflow_id: str,
    mode: str,
    stream_run,
    required_live_tools: list[str] | None,
    assumption_check: bool,
    draft: dict[str, Any] | None,
    phase: str,
) -> Any:
    last = stream_run(agent_id, run_id, on_event=on_event)
    ledger = StepLedger(draft)
    required = [tool_family(name) for name in (required_live_tools or []) if tool_family(name)]
    successful: set[str] = set()
    fail_counts: dict[str, int] = {}
    unreachable: set[str] = set()
    last_errors: dict[str, str] = {}
    nudge_without_call = 0
    did_assumption_check = False
    result_cache: dict[str, dict[str, Any]] = {}
    max_rounds = _MAX_ROUNDS_EXECUTE if mode == "execute" else _MAX_ROUNDS_PLAN

    def missing_required() -> list[str]:
        return [
            name
            for name in required
            if not _covers_required(name, successful) and name not in unreachable
        ]

    for _round_n in range(max_rounds):
        last_text = getattr(last, "text", None) or ""
        if _should_pause_for_clarify(last_text):
            return _attach_live_ok(last, successful, ledger)
        calls = should_run_tool_calls(last_text, mode=mode)
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
                run = cursor_client.create_run_when_ready(
                    agent_id,
                    prompt=follow,
                    mode="agent",
                    previous_run_id=str(getattr(last, "run_id", "") or run_id),
                )
                next_id = str(run.get("id") or "")
                if not next_id:
                    return _attach_live_ok(last, successful, ledger)
                last = stream_run(agent_id, next_id, on_event=on_event)
                continue
            return _attach_live_ok(last, successful, ledger)
        if not calls:
            return _attach_live_ok(last, successful, ledger)

        if did_assumption_check:
            fresh: list[dict[str, Any]] = []
            for call in calls:
                name = str(call.get("name") or "")
                family = tool_family(name)
                cache_key = _tool_cache_key(name, call.get("arguments") or {})
                if family and family in successful and not _is_helper_tool(name):
                    continue
                if cache_key in result_cache:
                    continue
                fresh.append(call)
            if not fresh:
                return _attach_live_ok(last, successful, ledger)
            calls = fresh

        nudge_without_call = 0
        results: list[dict[str, Any]] = []
        for call in calls[:_MAX_CALLS_PER_ROUND]:
            name = str(call.get("name") or "")
            family = tool_family(name)
            arguments = call.get("arguments") or {}
            step = ledger.resolve(call) if ledger.enabled else None
            rejection = _reject_off_phase(phase, name) or _reject_off_contract(step, name)
            if rejection:
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "step": str((step or {}).get("id") or ""),
                        "validation": {
                            "data_status": "mismatch",
                            "reasons": [rejection],
                            "next_action": "Возьми инструмент из разрешённых для этого шага.",
                        },
                        "error": rejection,
                    }
                )
                _emit(on_event, "decision", f"«{name}» отклонён: {rejection}")
                continue
            cache_key = _tool_cache_key(name, arguments)
            cached = result_cache.get(cache_key)
            if cached is not None:
                results.append({**cached, "cached": True})
                summary = _format_tool_output(
                    name,
                    cached.get("result") if isinstance(cached.get("result"), dict) else {},
                )
                _emit(on_event, "tool_result", f"{name}\n{summary} (уже было)")
                _emit(on_event, "decision", f"«{name}»: уже есть, повтор не нужен.")
                continue
            _emit(on_event, "decision", f"Cursor вызывает «{name}»…")
            if name.startswith("turboproject") or name == "turboproject":
                _emit(
                    on_event,
                    "decision",
                    "«turboproject»: читаю проекты на сервере Constructor "
                    "(это может занять до минуты)…",
                )
            if name in {"users.list", "users"}:
                _emit(
                    on_event,
                    "decision",
                    "«users.list»: читаю справочник пользователей…",
                )
            if name in {"users.current", "current_user"}:
                _emit(
                    on_event,
                    "decision",
                    "«users.current»: читаю текущего пользователя…",
                )
            if name in {"notify.send", "notify"}:
                _emit(
                    on_event,
                    "decision",
                    "«notify.send»: отправляю уведомление на компьютер…",
                )
            try:
                result = invoke_creation_tool(
                    tool=name,
                    arguments=arguments,
                    on_event=on_event,
                    workflow_id=workflow_id,
                )
                clipped = _clip_result(result)
                verdict = _verdict_for(
                    step=step,
                    name=name,
                    arguments=arguments,
                    result=result,
                    next_step=ledger.next_step(str((step or {}).get("id") or "")) if step else None,
                )
                ledger.record(step=step, name=name, verdict=verdict)
                packed = {
                    "name": name,
                    "ok": True,
                    "result": clipped,
                    "step": str((step or {}).get("id") or ""),
                    "validation": verdict.to_dict(),
                }
                results.append(packed)
                result_cache[cache_key] = packed
                # Успешный вызов не доказывает выполнение шага — только вердикт.
                if family and verdict.accepted and not _is_helper_tool(name):
                    successful.add(family)
                    fail_counts[family] = 0
                    unreachable.discard(family)
                summary = _format_tool_output(name, result if isinstance(result, dict) else clipped)
                _emit(
                    on_event,
                    "tool_result",
                    f"{name}\n{summary}",
                    {"tool": name, "result": clipped, "validation": verdict.to_dict()},
                )
                if verdict.accepted:
                    _emit(on_event, "decision", f"«{name}»: готово.")
                else:
                    reason = "; ".join(verdict.reasons) or verdict.data_status
                    _emit(
                        on_event,
                        "decision",
                        f"«{name}»: данные не приняты ({verdict.data_status}) — {reason}",
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Creation tool %s failed: %s", name, exc)
                ledger.record(step=step, name=name, verdict=None, error=str(exc))
                results.append(
                    {
                        "name": name,
                        "ok": False,
                        "error": str(exc),
                        "step": str((step or {}).get("id") or ""),
                        "validation": {
                            "data_status": "mismatch",
                            "reasons": [str(exc)[:300]],
                            "next_action": "Исправь параметры или выбери другой инструмент шага.",
                        },
                    }
                )
                if family:
                    fail_counts[family] = fail_counts.get(family, 0) + 1
                    last_errors[family] = str(exc)
                    if fail_counts[family] >= _MAX_TOOL_FAILURES:
                        unreachable.add(family)
                _emit(
                    on_event,
                    "tool_result",
                    f"{name}\n{exc}",
                    {"tool": name, "ok": False},
                )
                _emit(on_event, "decision", f"«{name}»: {exc}")
        pending = missing_required()
        accepted = [
            item
            for item in results
            if item.get("ok")
            and str((item.get("validation") or {}).get("data_status") or "complete")
            in {"complete", "empty_valid"}
        ]
        any_ok = bool(accepted)
        steps_left = ledger.missing_required() if ledger.enabled else []
        if (
            assumption_check
            and mode == "execute"
            and not did_assumption_check
            and any_ok
            and not pending
            and not steps_left
        ):
            did_assumption_check = True
            follow = _assumption_check_prompt(results)
        else:
            follow = _followup_prompt(
                results,
                mode=mode,
                pending=pending,
                unreachable=sorted(unreachable),
                last_errors=last_errors,
                steps_left=steps_left,
            )
        run = cursor_client.create_run_when_ready(
            agent_id,
            prompt=follow,
            mode="agent",
            previous_run_id=str(getattr(last, "run_id", "") or run_id),
        )
        next_id = str(run.get("id") or "")
        if not next_id:
            return _attach_live_ok(last, successful, ledger)
        last = stream_run(agent_id, next_id, on_event=on_event)
    return _attach_live_ok(last, successful, ledger)


def _reject_off_phase(phase: str, name: str) -> str:
    """Фазу объявляет контракт: на проектировании бизнес-данные не читаем."""
    from app.services.local_mcp import tool_contracts

    contract = tool_contracts().get(name)
    if contract is None:
        return ""
    if phase in (contract.get("phases") or []):
        return ""
    return (
        f"{name} недоступен на этапе проектирования "
        f"({contract.get('system')}·{contract.get('entity')}·{contract.get('operation')}). "
        "Опиши шаг в черновике, данные возьмём в пробном прогоне."
    )


def _is_helper_tool(name: str) -> bool:
    from app.services.local_mcp import tool_contracts

    return bool((tool_contracts().get(name) or {}).get("helper"))


def _reject_off_contract(step: dict[str, Any] | None, name: str) -> str:
    """Вызов вне кандидатов шага не исполняем — это ошибка выбора инструмента."""
    if _is_helper_tool(name):
        return ""
    if step is None:
        return ""
    candidates = [str(item) for item in (step.get("tool_candidates") or [])]
    if not candidates or name in candidates:
        return ""
    return (
        f"{name} не подходит шагу {step.get('id')} "
        f"({step.get('system')}·{step.get('entity')}·{step.get('operation')}). "
        f"Кандидаты: {', '.join(candidates)}"
    )


def _verdict_for(
    *,
    step: dict[str, Any] | None,
    name: str,
    arguments: dict[str, Any],
    result: Any,
    next_step: dict[str, Any] | None,
) -> Any:
    from app.services.workflows.tool_result_validation import evaluate_tool_result

    return evaluate_tool_result(
        step=step,
        name=name,
        arguments=arguments,
        result=result,
        next_step=next_step,
    )


def _attach_live_ok(last: Any, successful: set[str], ledger: "StepLedger | None" = None) -> Any:
    names = sorted(successful)
    if last is not None and hasattr(last, "successful_live_tools"):
        last.successful_live_tools = names
    if last is not None and ledger is not None and ledger.enabled:
        try:
            last.step_ledger = ledger.as_list()
        except AttributeError:
            pass
    return last


def _nudge_live_tools_prompt(pending: list[str]) -> str:
    names = ", ".join(pending)
    return (
        "Ты ещё не получил ответ Constructor tool для: "
        f"{names}.\n"
        "Не используй BACKEND_URL, curl и HTTP с Cloud VM — на VM их нет, это не FAIL.\n"
        "Верни ТОЛЬКО один блок ```constructor_tool с name из разрешённых для шага "
        f"(сейчас нужен {names}). Дождись фактов от backend, не останавливайся."
    )


def _verdict_lines(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in results:
        validation = item.get("validation") if isinstance(item.get("validation"), dict) else {}
        status = str(validation.get("data_status") or "")
        if not status or status in {"complete", "empty_valid"}:
            continue
        reasons = "; ".join(str(r) for r in (validation.get("reasons") or []))
        action = str(validation.get("next_action") or "")
        step = str(item.get("step") or "")
        head = f"- {item.get('name')}" + (f" (шаг {step})" if step else "")
        lines.append(f"{head}: {status}. {reasons}. {action}".strip())
    if not lines:
        return ""
    return (
        "Проверка данных не пройдена:\n"
        + "\n".join(lines)
        + "\nЭто не выполненные шаги. Не делай выводов по этим данным и не переходи дальше: "
        "исправь параметры, дочитай страницы, возьми другой инструмент шага "
        "или обработай полный набор кодом (helper constructor · dataset · execute). "
        "Если признак должен быть в данных, но неясно где его искать и в материалах этого нет — "
        "CLARIFY с 2–4 вариантами. "
        "FAILED_VALIDATION — когда источник ответил, обработка сделана, "
        "и либо человек уже ответил, либо спрашивать нечего.\n"
    )


def _followup_prompt(
    results: list[dict[str, Any]],
    *,
    mode: str,
    pending: list[str] | None = None,
    unreachable: list[str] | None = None,
    last_errors: dict[str, str] | None = None,
    steps_left: list[str] | None = None,
) -> str:
    blob = json.dumps(results, ensure_ascii=False, indent=2, default=str)
    verdicts = _verdict_lines(results)
    if steps_left:
        verdicts += (
            "Ещё не закрыты обязательные шаги: "
            + ", ".join(steps_left)
            + ". Итог и example_run до этого не пиши.\n"
        )
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
        done = [str(item.get("name") or "") for item in results if item.get("ok")]
        done_line = ", ".join(name for name in done if name)
        tail = (
            "Учти результаты Constructor tools. "
            + (
                f"Уже получены данные от: {done_line}. "
                "Не вызывай эти tools снова с теми же или пустыми args. "
                if done_line
                else ""
            )
            + "Если решение (кого/что брать, когда/как часто, в каком виде отдавать) "
            "не сказано в ТЗ — верни CLARIFY и остановись, не обрабатывай весь каталог. "
            "Если это уже явно в ТЗ или человек ответил — предметный RESULT: текст обязателен, "
            "плюс файлы/действия/уведомления если они были. "
            "Если в задаче сказано «текущий пользователь», «данный пользователь», «мои проекты» "
            "или «мои задачи» — сначала вызови users.current. "
            "Не вызывай users.list / turboproject «на всякий случай». "
            "Если нужен ДРУГОЙ tool — только ```constructor_tool. "
            "Не ставь FAIL из-за отсутствия BACKEND_URL на Cloud VM."
        )
    return (
        "Результаты вызовов инструментов Constructor (факты с сервера/desktop, не с VM):\n"
        f"{blob}\n\n{verdicts}{tail}"
    )


def _assumption_check_prompt(results: list[dict[str, Any]]) -> str:
    blob = json.dumps(results, ensure_ascii=False, indent=2, default=str)
    return (
        "Результаты вызовов инструментов Constructor (факты с сервера/desktop, не с VM):\n"
        f"{blob}\n\n"
        "Это только подсмотр. Не разбирай весь каталог и не считай итог.\n"
        "Перечисли допущения, которых не было в ТЗ и которые меняют расчёт: "
        "кого/что брать, когда и как часто запускать, в каком виде и кому отдавать, "
        "что считать успехом.\n"
        "Если хотя бы одно такое допущение ты только что принял сам — верни ТОЛЬКО CLARIFY "
        "и остановись. Не вызывай constructor_tool в этом ответе и не повторяй уже успешный tool.\n"
        "Если каждое из этих решений уже явно сказано в материалах — напиши это "
        "и продолжи с указанным объёмом, без default «все».\n"
        "Не спрашивай про поля, OData, COM и имена tools."
    )


def is_directory_search_query(query: str) -> bool:
    """True if query looks like ФИО / email / id, not a role or «все»."""
    raw = (query or "").strip()
    if len(raw) < 3:
        return False
    if "@" in raw:
        return True
    if any(ch.isdigit() for ch in raw) and len(raw) >= 4:
        return True
    words = [part for part in re.split(r"\s+", raw) if part]
    if len(words) >= 2:
        return True
    low = raw.casefold()
    if any(hint in low for hint in _GENERIC_USER_QUERIES):
        return False
    return len(raw) >= 4


def normalize_users_list_query(arguments: dict[str, Any] | None) -> tuple[str, str]:
    query = str((arguments or {}).get("query") or (arguments or {}).get("search") or "").strip()
    if not query:
        return "", ""
    if is_directory_search_query(query):
        return query, ""
    return "", query


def _tool_cache_key(name: str, arguments: dict[str, Any] | None) -> str:
    args = dict(arguments or {})
    args.pop("workflow_id", None)
    args.pop("agent_id", None)
    if name in {"users.list", "users"}:
        search, _ignored = normalize_users_list_query(args)
        args = {"query": search} if search else {}
    try:
        return json.dumps({"name": name, "args": args}, sort_keys=True, ensure_ascii=False)
    except TypeError:
        return f"{name}:{args}"


def _invoke_notify_send(arguments: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.schemas.notification import NotificationCreate
    from app.services.notifications.service import create_notification

    ctx = current_tool_context()
    sender = ctx[1] if ctx else ""
    if not sender:
        raise RuntimeError("Нет пользователя сессии для notify.send")
    recipient = str(
        arguments.get("user_id")
        or arguments.get("recipient_user_id")
        or arguments.get("recipient")
        or arguments.get("fio")
        or ""
    ).strip()
    title = str(arguments.get("title") or "").strip()
    if not recipient or not title:
        raise RuntimeError("Для notify.send нужны user_id (из users.list) и title")
    payload = NotificationCreate(
        recipient_user_id=recipient,
        title=title,
        body=str(arguments.get("body") or ""),
        workflow_id=str(arguments.get("workflow_id") or arguments.get("agent_id") or ""),
    )
    send_at = str(arguments.get("send_at") or "").strip()
    if send_at:
        from datetime import datetime

        try:
            payload.send_at = datetime.fromisoformat(send_at.replace("Z", "+00:00"))
        except ValueError:
            payload.send_at = None
    db = SessionLocal()
    try:
        from app.services.notifications.service import NotificationError

        item = create_notification(db, sender_user_id=sender, payload=payload)
    except NotificationError as exc:
        raise RuntimeError(exc.message) from exc
    finally:
        db.close()
    return {
        "id": item.id,
        "ok": True,
        "delivered": "на компьютер получателя",
        "recipient_user_id": item.recipient_user_id,
        "title": item.title,
    }


def _invoke_users_list(arguments: dict[str, Any]) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.notifications.service import list_directory_users

    search, ignored = normalize_users_list_query(arguments)
    db = SessionLocal()
    try:
        items = list_directory_users(db, search=search)
    finally:
        db.close()
    payload: dict[str, Any] = {
        "users": [item.model_dump(mode="json") for item in items],
        "count": len(items),
    }
    if ignored:
        payload["ignored_query"] = ignored
    return payload


def _invoke_users_current() -> dict[str, Any]:
    from app.clients.erp_sql import ErpSqlError, find_user_by_id
    from app.db.session import SessionLocal
    from app.models.user import AppUser

    ctx = current_tool_context()
    user_id = ctx[1] if ctx else ""
    if not user_id:
        raise RuntimeError("Нет пользователя сессии для users.current")

    db = SessionLocal()
    try:
        app_user = db.get(AppUser, user_id)
        if app_user is not None:
            user = {
                "id": app_user.id,
                "fio": app_user.fio or "",
                "position": app_user.position or "",
                "department": app_user.department or "",
                "source": "constructor_session",
            }
            return {"user": user, "ok": True}
    finally:
        db.close()

    try:
        erp_user = find_user_by_id(user_id)
    except ErpSqlError as exc:
        raise RuntimeError(f"Не удалось прочитать текущего пользователя из ERP: {exc}") from exc
    if erp_user is None:
        raise RuntimeError("Текущий пользователь не найден в ERP")
    return {
        "user": {
            "id": erp_user.id,
            "fio": erp_user.fio,
            "position": erp_user.position,
            "department": erp_user.department,
            "source": "erp_pm",
        },
        "ok": True,
    }


def _row_title(row: Any) -> str:
    if isinstance(row, str):
        return row.strip()
    if not isinstance(row, dict):
        return str(row).strip()
    for key in ("name", "title", "fio", "email", "file", "path", "id", "projectName"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _format_tool_output(_name: str, result: dict[str, Any], *, limit: int = 1600) -> str:
    if not result:
        return "Готово"
    if result.get("delivered") or (
        _name in {"notify.send", "notify"} and result.get("ok") and result.get("id")
    ):
        title = str(result.get("title") or "").strip()
        return f"Готово · уведомление на компьютер" + (f": {title}" if title else "")
    labels = {
        "projects": "проектов",
        "users": "пользователей",
        "items": "записей",
        "results": "результатов",
        "documents": "документов",
        "cards": "карточек",
        "files": "файлов",
        "messages": "писем",
        "events": "событий",
    }
    for key, label in labels.items():
        value = result.get(key)
        if not isinstance(value, list):
            continue
        count = result.get("count", len(value))
        lines = [f"Готово · {count} {label}"]
        for row in value[:15]:
            title = _row_title(row)
            if title:
                lines.append(f"• {title}")
        extra = len(value) - 15
        if extra > 0:
            lines.append(f"… ещё {extra}")
        return "\n".join(lines)
    if result.get("truncated") and result.get("preview"):
        preview = str(result.get("preview") or "")
        return preview[:limit] + ("…" if len(preview) > limit else "")
    try:
        text = json.dumps(result, ensure_ascii=False, indent=2)
    except TypeError:
        text = str(result)
    if len(text) > limit:
        return text[:limit] + "…"
    return text or "Готово"


def _clip_result(result: dict[str, Any], limit: int = 8000) -> dict[str, Any]:
    registry = _datasets.get()
    if registry is not None:
        return registry.pack(result, limit=limit)
    try:
        raw = json.dumps(result, ensure_ascii=False, default=str)
    except TypeError:
        return {"text": str(result)[:limit]}
    if len(raw) <= limit:
        return result
    return {"truncated": True, "preview": raw[:limit] + "…"}


def _invoke_data_process(arguments: dict[str, Any]) -> dict[str, Any]:
    from app.services.workflows.data_sandbox import run_dataset_code

    registry = _datasets.get()
    if registry is None:
        raise RuntimeError("Нет набора данных этого прогона.")
    dataset_id = str(arguments.get("dataset_id") or registry.latest_id() or "").strip()
    data = registry.get(dataset_id)
    if data is None:
        raise RuntimeError(
            f"Набор {dataset_id or '—'} не найден. Сначала вызови инструмент шага."
        )
    outcome = run_dataset_code(code=str(arguments.get("code") or ""), data=data)
    if not outcome.get("ok"):
        raise RuntimeError(str(outcome.get("error") or "песочница"))
    return {"result": outcome.get("result"), "dataset_id": dataset_id}


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
