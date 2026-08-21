# Constructor-level agent creation prompts (RegAgent pipeline).
# Stubbed: triggers/KPI generation, schedule cron UI, playbook repair auto-loop.

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import ValidationError

from app.agent.dictionary import resolve_tools, validate_dictionary
from app.agent.json_parse import extract_json_object
from app.models import (
    Card,
    ChatCommand,
    ClarificationQuestion,
    DemoState,
    DemoStep,
    FunctionGroup,
    FunctionsData,
    PassportData,
    PassportField,
    Playbook,
    PlaybookDraft,
    PlaybookStep,
    UiAction,
    UiSpec,
)
from app.tools.registry import list_tool_definitions

_RESULT_BLOCK_RE = re.compile(
    r"RESULT:\s*\n(.*?)(?:\n(?:FILES|ACTIONS|NOTIFICATIONS|SCHEDULE|CLARIFY):|\Z)",
    re.DOTALL | re.IGNORECASE,
)
_CLARIFY_BLOCK_RE = re.compile(
    r"CLARIFY:\s*\n(.*?)(?:\n(?:RESULT|FILES|ACTIONS):|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_TECHNICAL_CLARIFY_MARKERS = (
    "odata",
    "com",
    "curl",
    "shell",
    "api_key",
    "guid",
    "entity",
    "mcp",
    "constructor_integrations",
    "registry",
    "tool=",
)


def _clip(text: str, limit: int = 12000) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit] + "\n\n[... текст обрезан ...]"


def _tool_catalog() -> str:
    lines = ["Доступные custom-инструменты (constructor_integrations):"]
    for defn in list_tool_definitions():
        lines.append(f"- {defn.name}: {defn.description}")
    lines.append(
        "Поручения документооборота: только onec.docflow_tasks (OData). "
        "Не используй COM search_* для поручений."
    )
    return "\n".join(lines)


def filter_technical_clarify(questions: list[ClarificationQuestion]) -> list[ClarificationQuestion]:
    kept: list[ClarificationQuestion] = []
    for q in questions:
        blob = f"{q.question} {' '.join(q.options)}".casefold()
        if any(marker in blob for marker in _TECHNICAL_CLARIFY_MARKERS):
            continue
        kept.append(q)
    return kept


def build_functions_prompt(*, regulation_text: str, file_name: str = "") -> str:
    return (
        "Проанализируй регламент и выдели функциональные группы процессов для ИИ-агента.\n"
        "Каждая группа — отдельный сценарий (например: поручения, календарь, почта).\n"
        "Для каждой группы укажи system, entity, operations и tools из каталога.\n"
        "Верни ТОЛЬКО JSON:\n"
        "{\n"
        '  "title": "название агента",\n'
        '  "summary": "кратко",\n'
        '  "groups": [\n'
        "    {\n"
        '      "id": "g1",\n'
        '      "title": "...",\n'
        '      "summary": "...",\n'
        '      "system": "outlook|onec",\n'
        '      "entity": "calendar|porucheniya|mail",\n'
        '      "operations": ["read_calendar"],\n'
        '      "tools": ["outlook.read_calendar"]\n'
        "    }\n"
        "  ]\n"
        "}\n\n"
        f"{_tool_catalog()}\n\n"
        f"Файл: {file_name or 'regulation'}\n"
        "===== РЕГЛАМЕНТ =====\n"
        f"{_clip(regulation_text)}\n"
        "===== КОНЕЦ ====="
    )


def build_passport_prompt(*, card: Card, group: FunctionGroup | None = None) -> str:
    group_block = ""
    if group is not None:
        group_block = (
            f"\nВыбранная функция: {group.title}\n"
            f"system={group.system}, entity={group.entity}, "
            f"operations={group.operations}, tools={group.tools}\n"
        )
    return (
        "Составь паспорт ИИ-агента по регламенту.\n"
        "Верни ТОЛЬКО JSON:\n"
        "{\n"
        '  "title": "...",\n'
        '  "goal": "миссия агента",\n'
        '  "summary": "...",\n'
        '  "system": "outlook|onec",\n'
        '  "entity": "...",\n'
        '  "operations": ["..."],\n'
        '  "tools": ["outlook.read_calendar"],\n'
        '  "fields": [{"id":"f1","label":"...","value":"...","required":true}]\n'
        "}\n\n"
        f"{_tool_catalog()}\n"
        f"{group_block}\n"
        "===== РЕГЛАМЕНТ =====\n"
        f"{_clip(card.regulation_text)}\n"
        "===== КОНЕЦ ====="
    )


def build_passport_questions_prompt(*, card: Card) -> str:
    passport = card.passport
    return (
        "По паспорту агента сформулируй до 3 вопросов пользователю.\n"
        "Только то, что может решить человек (кому слать, как часто, что считать успехом).\n"
        "Не спрашивай про OData/COM/API/URL/пароли.\n"
        "Верни ТОЛЬКО JSON:\n"
        '{"questions":[{"id":"q1","question":"...","options":["..."],"allow_free_text":true}]}\n\n'
        f"Паспорт: {passport.model_dump_json(ensure_ascii=False)}\n"
        "===== РЕГЛАМЕНТ =====\n"
        f"{_clip(card.regulation_text, 6000)}\n"
        "===== КОНЕЦ ====="
    )


def build_playbook_draft_prompt(*, card: Card) -> str:
    return (
        "Составь черновик playbook — пошаговый сценарий работы агента.\n"
        "Каждый шаг: id, title, action, tool (из каталога), done_when.\n"
        "Верни ТОЛЬКО JSON:\n"
        "{\n"
        '  "status": "draft",\n'
        '  "tools": ["outlook.read_calendar"],\n'
        '  "steps": [\n'
        '    {"id":"s1","title":"...","action":"...","tool":"outlook.read_calendar","done_when":"..."}\n'
        "  ]\n"
        "}\n\n"
        f"{_tool_catalog()}\n\n"
        f"Паспорт:\n{card.passport.model_dump_json(ensure_ascii=False)}\n"
        "===== РЕГЛАМЕНТ =====\n"
        f"{_clip(card.regulation_text, 8000)}\n"
        "===== КОНЕЦ ====="
    )


def build_playbook_repair_prompt(*, card: Card, errors: list[str]) -> str:
    return (
        "Исправь playbook по ошибкам валидации.\n"
        "Верни ТОЛЬКО JSON playbook_draft (status, tools, steps).\n\n"
        f"Ошибки:\n" + "\n".join(f"- {e}" for e in errors) + "\n\n"
        f"Текущий черновик:\n{card.playbook_draft.model_dump_json(ensure_ascii=False)}\n"
        f"{_tool_catalog()}"
    )


def build_demo_system(card: Card) -> str:
    passport = card.passport
    playbook = card.playbook_draft
    return (
        "Ты демо-агент RegAgent. Выполняй шаги playbook реальными вызовами инструментов.\n"
        "Для 1C/Outlook — constructor_integrations (tool + arguments).\n"
        "Поручения — только onec.docflow_tasks.\n"
        "Запись в Outlook (create_event) требует подтверждения человека.\n"
        "По завершении шага верни блок RESULT:\n"
        "RESULT:\n"
        "<что сделано>\n"
        "CLARIFY:\n"
        "- вопрос пользователю (только если нужно)\n\n"
        f"Паспорт: title={passport.title}, goal={passport.goal}\n"
        f"Playbook steps: {[s.model_dump() for s in playbook.steps]}\n"
        f"Tools: {playbook.tools}\n"
        f"Rules:\n{(card.rules_prompt or card.ui_spec.rules_prompt or '').strip()}"
    )


def build_demo_prompt(*, card: Card) -> str:
    steps = card.playbook_draft.steps
    if not steps:
        return "Выполни типовой сценарий агента по регламенту и верни RESULT."
    first = steps[0]
    return (
        f"Демо: выполни шаг «{first.title}».\n"
        f"Действие: {first.action}\n"
        f"Инструмент: {first.tool or 'подбери сам'}\n"
        "Вызови инструмент, затем RESULT."
    )


def build_demo_continue_prompt(*, card: Card, step_index: int) -> str:
    steps = card.playbook_draft.steps
    if step_index >= len(steps):
        return "Все шаги выполнены. Подведи итог демо и верни RESULT с ok=true."
    step = steps[step_index]
    return (
        f"Продолжи демо — шаг {step_index + 1}/{len(steps)}: «{step.title}».\n"
        f"Действие: {step.action}\n"
        f"Инструмент: {step.tool or 'подбери сам'}"
    )


def build_published_run_prompt(*, card: Card, user_message: str) -> str:
    return (
        f"Задача пользователя:\n{user_message.strip()}\n\n"
        f"Playbook:\n{card.playbook.model_dump_json(ensure_ascii=False)}"
    )


def build_ui_spec_from_pipeline(card: Card) -> UiSpec:
    """UiSpec из passport + playbook (основной путь публикации)."""
    passport = card.passport
    playbook = card.playbook
    actions: list[UiAction] = []
    for step in playbook.steps[:8]:
        actions.append(
            UiAction(
                id=step.id or f"step_{len(actions)}",
                label=step.title or step.action[:40] or "Действие",
                hint=step.done_when[:80] if step.done_when else "",
                prompt=step.action or step.title,
                tools_hint=[step.tool] if step.tool else [],
            )
        )
    if not actions:
        actions.append(
            UiAction(
                id="main",
                label="Выполнить по регламенту",
                hint="Основной сценарий",
                prompt=passport.goal or card.summary or "Выполни задачу по регламенту.",
                tools_hint=playbook.tools or passport.tools,
            )
        )
    rules = (
        f"Цель: {passport.goal}\n"
        f"Система: {passport.system}, сущность: {passport.entity}\n"
        f"Инструменты: {', '.join(playbook.tools or passport.tools)}\n"
        f"{card.regulation_text[:4000]}"
    ).strip()
    return UiSpec(
        title=passport.title or card.title or "ИИ-агент",
        summary=passport.summary or card.summary,
        rules_prompt=rules,
        needs_clarification=[],
        actions=actions,
        chat_commands=[
            ChatCommand(command="/help", description="Список команд"),
        ],
    )


def parse_functions_result(text: str) -> FunctionsData:
    data = extract_json_object(text)
    groups_raw = data.get("groups") or []
    groups: list[FunctionGroup] = []
    for item in groups_raw:
        if not isinstance(item, dict):
            continue
        tools = list(item.get("tools") or [])
        if not tools:
            tools = resolve_tools(
                system=str(item.get("system") or ""),
                entity=str(item.get("entity") or ""),
                operations=list(item.get("operations") or []),
            )
        groups.append(
            FunctionGroup(
                id=str(item.get("id") or f"g{len(groups)+1}"),
                title=str(item.get("title") or "Процесс"),
                summary=str(item.get("summary") or ""),
                system=str(item.get("system") or ""),
                entity=str(item.get("entity") or ""),
                operations=[str(o) for o in (item.get("operations") or [])],
                tools=tools,
            )
        )
    return FunctionsData(
        groups=groups,
        title=str(data.get("title") or ""),
        summary=str(data.get("summary") or ""),
    )


def parse_passport_result(text: str) -> PassportData:
    data = extract_json_object(text)
    fields_raw = data.get("fields") or []
    fields: list[PassportField] = []
    for item in fields_raw:
        if isinstance(item, dict):
            fields.append(
                PassportField(
                    id=str(item.get("id") or f"f{len(fields)+1}"),
                    label=str(item.get("label") or ""),
                    value=str(item.get("value") or ""),
                    required=bool(item.get("required", True)),
                )
            )
    tools = [str(t) for t in (data.get("tools") or [])]
    if not tools:
        tools = resolve_tools(
            system=str(data.get("system") or ""),
            entity=str(data.get("entity") or ""),
            operations=[str(o) for o in (data.get("operations") or [])],
        )
    return PassportData(
        title=str(data.get("title") or ""),
        goal=str(data.get("goal") or ""),
        summary=str(data.get("summary") or ""),
        system=str(data.get("system") or ""),
        entity=str(data.get("entity") or ""),
        operations=[str(o) for o in (data.get("operations") or [])],
        tools=tools,
        fields=fields,
    )


def parse_passport_questions(text: str) -> list[ClarificationQuestion]:
    data = extract_json_object(text)
    raw = data.get("questions") or []
    out: list[ClarificationQuestion] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        out.append(
            ClarificationQuestion(
                id=str(item.get("id") or f"q{len(out)+1}"),
                question=str(item.get("question") or ""),
                options=[str(o) for o in (item.get("options") or [])],
                allow_free_text=bool(item.get("allow_free_text", True)),
            )
        )
    return filter_technical_clarify(out)


def parse_playbook_draft(text: str) -> PlaybookDraft:
    data = extract_json_object(text)
    steps_raw = data.get("steps") or []
    steps: list[PlaybookStep] = []
    for item in steps_raw:
        if isinstance(item, dict):
            steps.append(
                PlaybookStep(
                    id=str(item.get("id") or f"s{len(steps)+1}"),
                    title=str(item.get("title") or ""),
                    action=str(item.get("action") or ""),
                    tool=str(item.get("tool") or ""),
                    done_when=str(item.get("done_when") or ""),
                )
            )
    tools = [str(t) for t in (data.get("tools") or [])]
    if not tools and steps:
        tools = [s.tool for s in steps if s.tool]
    return PlaybookDraft(
        status=str(data.get("status") or "draft"),
        steps=steps,
        tools=tools,
        raw=text[:8000],
    )


def validate_playbook_draft(draft: PlaybookDraft, passport: PassportData) -> PlaybookDraft:
    validation = validate_dictionary(
        system=passport.system,
        entity=passport.entity,
        operations=passport.operations,
        tools=draft.tools or passport.tools,
    )
    errors = list(validation.errors)
    for step in draft.steps:
        if step.tool and step.tool not in validation.tools and step.tool not in {
            d.name for d in list_tool_definitions()
        }:
            errors.append(f"Шаг {step.id}: неизвестный tool {step.tool}")
    if errors:
        return draft.model_copy(update={"status": "failed", "errors": errors})
    return draft.model_copy(update={"status": "verified", "errors": [], "tools": validation.tools})


def playbook_from_draft(draft: PlaybookDraft, passport: PassportData) -> Playbook:
    return Playbook(
        version=1,
        steps=list(draft.steps),
        tools=list(draft.tools or passport.tools),
        goal=passport.goal,
    )


def parse_result_block(text: str) -> dict[str, Any]:
    raw = text or ""
    match = _RESULT_BLOCK_RE.search(raw)
    body = match.group(1).strip() if match else raw.strip()
    clarify_match = _CLARIFY_BLOCK_RE.search(raw)
    clarify_lines: list[str] = []
    if clarify_match:
        clarify_lines = [
            line.strip().lstrip("-•").strip()
            for line in clarify_match.group(1).splitlines()
            if line.strip()
        ]
    ok = bool(body) and "ошибк" not in body.casefold()[:120]
    return {
        "text": body,
        "ok": ok,
        "clarify": filter_technical_clarify(
            [
                ClarificationQuestion(id=f"c{i+1}", question=q, options=[], allow_free_text=True)
                for i, q in enumerate(clarify_lines)
                if q
            ]
        ),
    }


def parse_demo_result(text: str, *, steps_count: int = 0) -> DemoState:
    parsed = parse_result_block(text)
    demo_steps: list[DemoStep] = []
    if steps_count:
        demo_steps.append(
            DemoStep(
                id="demo_step",
                title="Демо",
                ok=parsed["ok"],
                detail=str(parsed.get("text") or "")[:500],
            )
        )
    return DemoState(
        ok=bool(parsed.get("ok")),
        verified=bool(parsed.get("ok")),
        steps=demo_steps,
        transcript=[text[:4000]] if text else [],
        result=dict(parsed),
        error="" if parsed.get("ok") else str(parsed.get("text") or "Демо не прошло"),
    )


def parse_json_safe(text: str) -> dict[str, Any]:
    try:
        return extract_json_object(text)
    except (ValueError, json.JSONDecodeError, ValidationError):
        return {}
