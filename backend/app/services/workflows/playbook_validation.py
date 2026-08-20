"""Проверка полноты чернового playbook до запуска на живых данных.

Три класса проблем не смешиваются:
- clarify — не определён бизнес-параметр, спрашиваем человека;
- config_error — нет совместимого инструмента или параметров, это ошибка конфигурации;
- ambiguous — шаг описан неоднозначно, возвращаем проектировщику.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.workflow_tool_routing import (
    normalize_entity,
    normalize_operation,
    select_candidates,
)
from app.services.workflows.plan_models import OpenQuestion
from app.services.workflows.schedule_draft import (
    WHEN_TO_RUN_OPTIONS,
    WHEN_TO_RUN_QUESTION,
    WHEN_TO_RUN_WHY,
    already_asks_when_to_run,
    explicit_when_to_run,
)

KIND_CLARIFY = "clarify"
KIND_CONFIG_ERROR = "config_error"
KIND_AMBIGUOUS = "ambiguous"


@dataclass
class DraftIssue:
    kind: str
    message: str
    step_id: str = ""
    detail: str = ""
    options: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "step_id": self.step_id,
            "detail": self.detail,
            "options": list(self.options),
        }


@dataclass
class DraftValidation:
    issues: list[DraftIssue] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[DraftIssue]:
        return [item for item in self.issues if item.kind == kind]

    @property
    def clarifications(self) -> list[DraftIssue]:
        return self.of_kind(KIND_CLARIFY)

    @property
    def config_errors(self) -> list[DraftIssue]:
        return self.of_kind(KIND_CONFIG_ERROR)

    @property
    def ambiguous(self) -> list[DraftIssue]:
        return self.of_kind(KIND_AMBIGUOUS)

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "issues": [item.to_dict() for item in self.issues],
            "clarify_count": len(self.clarifications),
            "config_error_count": len(self.config_errors),
            "ambiguous_count": len(self.ambiguous),
        }


# Ссылки, которые шаг не придумывает: их обязан отдать предыдущий шаг или вход черновика.
_REF_PARAMS = frozenset(
    {
        "user_id",
        "task_ref",
        "document_ref",
        "document_ref_key",
        "uid",
        "message_id",
        "file_id",
        "ref_key",
        "trigger_id",
        "browser_id",
    }
)

# Поле результата → какие входы следующих шагов оно закрывает.
_PROVIDES_TO_PARAMS = {
    "users": ("user_id", "user"),
    "user": ("user_id",),
    "projects": ("project_id", "file_id"),
    "tasks": ("task_ref", "task_id"),
    "task": ("task_ref", "task_id"),
    "documents": ("document_ref", "document_ref_key"),
    "document": ("document_ref", "document_ref_key"),
    "messages": ("uid", "message_id"),
    "files": ("file_id",),
    "id": ("id", "trigger_id"),
}


def _string_list(raw: Any) -> list[str]:
    return [str(item).strip() for item in (raw or []) if str(item).strip()]


def _parse_needs_from(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, str) and "." in item:
            step_id, field = item.split(".", 1)
            step_id, field = step_id.strip(), field.strip()
            if step_id and field:
                out.append({"step": step_id, "field": field, "as": field})
            continue
        if not isinstance(item, dict):
            continue
        step_id = str(item.get("step") or "").strip()
        field = str(item.get("field") or "").strip()
        dest = str(item.get("as") or field).strip()
        if step_id and field:
            out.append({"step": step_id, "field": field, "as": dest})
    return out


def _default_provides(candidates: list[str]) -> list[str]:
    from app.services.local_mcp import tool_contracts

    contracts = tool_contracts()
    fields: list[str] = []
    for name in candidates:
        for field in (contracts.get(name) or {}).get("result_fields") or []:
            text = str(field).strip()
            if text and text not in fields:
                fields.append(text)
    return fields


def _expand_provided(fields: list[str]) -> set[str]:
    offered = {str(field).strip().casefold() for field in fields if str(field).strip()}
    extra: set[str] = set()
    for field in offered:
        extra.update(alias.casefold() for alias in _PROVIDES_TO_PARAMS.get(field, ()))
    return offered | extra


def _ref_params_of(step: dict[str, Any], candidates: list[str]) -> list[str]:
    from app.services.local_mcp import tool_contracts

    contracts = tool_contracts()
    params: list[str] = []
    seen: set[str] = set()
    for name in candidates:
        for item in (contracts.get(name) or {}).get("required_filters") or []:
            text = str(item).strip()
            key = text.casefold()
            if key in _REF_PARAMS and key not in seen:
                seen.add(key)
                params.append(text)
    for item in step.get("required_params") or []:
        text = str(item).strip()
        key = text.casefold()
        if key in _REF_PARAMS and key not in seen:
            seen.add(key)
            params.append(text)
    return params


def _step_system(step: dict[str, Any]) -> str:
    return str(step.get("system") or "").strip().casefold()


def _step_entity(step: dict[str, Any]) -> str:
    return normalize_entity(str(step.get("entity") or ""))


def _step_operation(step: dict[str, Any]) -> str:
    return normalize_operation(str(step.get("operation") or ""))


def _is_calendar_create(step: dict[str, Any]) -> bool:
    return (
        _step_system(step) == "outlook"
        and _step_entity(step) == "calendar_event"
        and _step_operation(step) == "create"
    )


def _is_calendar_list(step: dict[str, Any]) -> bool:
    return (
        _step_system(step) == "outlook"
        and _step_entity(step) == "calendar_event"
        and _step_operation(step) == "list"
    )


def _calendar_list_step(step_id: str, *, title: str, purpose: str) -> dict[str, Any]:
    return {
        "id": step_id,
        "title": title,
        "required": True,
        "system": "outlook",
        "entity": "calendar_event",
        "operation": "list",
        "required_params": [],
        "data_expectation": "события календаря за широкий период и свободные слоты",
        "done_when": purpose,
        "on_empty": "если встреч нет — это валидный ответ только до записи; после create пусто недопустимо",
        "on_error": "повторить чтение календаря",
        "provides": ["events", "free_slots"],
    }


def _ensure_calendar_list_around_create(draft: dict[str, Any]) -> dict[str, Any]:
    """Перед записью в Outlook нужна занятость, после — проверка, что встречи видны."""
    steps = [step for step in (draft.get("steps") or []) if isinstance(step, dict)]
    create_indexes = [index for index, step in enumerate(steps) if _is_calendar_create(step)]
    if not create_indexes:
        return draft
    first_create = create_indexes[0]
    last_create = create_indexes[-1]
    has_list_before = any(_is_calendar_list(step) for step in steps[:first_create])
    has_list_after = any(_is_calendar_list(step) for step in steps[last_create + 1 :])
    out = list(steps)
    if not has_list_after:
        verify = _calendar_list_step(
            _next_step_id(out),
            title="Проверить записанные встречи",
            purpose="новые встречи видны в календаре",
        )
        insert_at = last_create + 1
        out = out[:insert_at] + [verify] + out[insert_at:]
    if not has_list_before:
        occupancy = _calendar_list_step(
            _next_step_id(out),
            title="Прочитать занятость календаря",
            purpose="получены события и свободные слоты за период планирования",
        )
        out = out[:first_create] + [occupancy] + out[first_create:]
    return {**draft, "steps": out}


def _is_spreadsheet_export(step: dict[str, Any]) -> bool:
    if _step_operation(step) != "export":
        return False
    system = _step_system(step)
    entity = _step_entity(step)
    return system in {"desktop", "excel"} or entity == "spreadsheet"


def _is_notify_step(step: dict[str, Any]) -> bool:
    return _step_operation(step) == "notify" or _step_entity(step) == "notification"


def _next_step_id(steps: list[dict[str, Any]]) -> str:
    used = {str(step.get("id") or "") for step in steps}
    index = len(steps) + 1
    while f"s{index}" in used:
        index += 1
    return f"s{index}"


def _ensure_plan_file_for_calendar_create(draft: dict[str, Any]) -> dict[str, Any]:
    """Встречи в Outlook без файла плана — неполный результат. Добавляем выгрузку."""
    steps = [step for step in (draft.get("steps") or []) if isinstance(step, dict)]
    if not any(_is_calendar_create(step) for step in steps):
        return draft
    if any(_is_spreadsheet_export(step) for step in steps):
        return draft
    export_step = {
        "id": _next_step_id(steps),
        "title": "Сформировать файл плана совещаний",
        "required": True,
        "system": "desktop",
        "entity": "spreadsheet",
        "operation": "export",
        "required_params": ["filename"],
        "data_expectation": "xlsx с датами, темами и участниками запланированных встреч",
        "done_when": "файл создан, в результате есть путь к нему",
        "on_empty": "если встреч нет — файл с пояснением, что записей нет",
        "on_error": "повторить выгрузку",
        "provides": ["file"],
    }
    insert_at = next(
        (index for index, step in enumerate(steps) if _is_notify_step(step)),
        len(steps),
    )
    return {**draft, "steps": steps[:insert_at] + [export_step] + steps[insert_at:]}


def attach_handoff(draft: dict[str, Any]) -> dict[str, Any]:
    """Явная передача: что шаг отдаёт и какие ссылки берёт из предыдущих."""
    available: dict[str, str] = {}
    steps: list[dict[str, Any]] = []
    for step in draft.get("steps") or []:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "")
        candidates = [str(name) for name in (step.get("tool_candidates") or []) if str(name).strip()]
        provides = _string_list(step.get("provides")) or _default_provides(candidates)
        needs = _parse_needs_from(step.get("needs_from"))
        seen = {(item["step"], item["as"].casefold()) for item in needs}
        for param in _ref_params_of(step, candidates):
            source = available.get(param.casefold())
            if source and (source, param.casefold()) not in seen:
                needs.append({"step": source, "field": param, "as": param})
                seen.add((source, param.casefold()))
        for field in _expand_provided(provides):
            available[field] = step_id
        steps.append({**step, "provides": provides, "needs_from": needs})
    return {**draft, "steps": steps}


def attach_tool_candidates(draft: dict[str, Any], *, allow_web: bool = False) -> dict[str, Any]:
    """Проставить каждому шагу инструменты и передачу данных между шагами."""
    draft = _ensure_calendar_list_around_create(draft)
    draft = _ensure_plan_file_for_calendar_create(draft)
    steps = list(draft.get("steps") or [])
    enriched: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        next_step = steps[index + 1] if index + 1 < len(steps) else None
        candidates = select_candidates(
            step,
            next_step=next_step if isinstance(next_step, dict) else None,
            allow_web=allow_web,
        )
        enriched.append({**step, "tool_candidates": candidates})
    return attach_handoff({**draft, "steps": enriched})


def _handoff_hint(params: list[str]) -> str:
    lows = {item.casefold() for item in params}
    hints: list[str] = []
    if "user_id" in lows:
        hints.append("для уведомления сначала constructor · user · read или list")
    if lows & {"task_ref", "task_id"}:
        hints.append("для карточки задачи сначала onec · task · search или list")
    if lows & {"document_ref", "document_ref_key"}:
        hints.append("для карточки документа сначала onec · document · search")
    if "uid" in lows or "message_id" in lows:
        hints.append("для письма сначала imap · mail_message · search или list")
    return "; ".join(hints) or "Добавь шаг, который отдаёт эту ссылку, и укажи needs_from."


def _missing_params(step: dict[str, Any], candidates: list[str]) -> list[str]:
    """Параметры, без которых ни один кандидат не вызвать."""
    from app.services.local_mcp import tool_contracts

    contracts = tool_contracts()
    known = {
        str(param).strip().casefold()
        for param in (step.get("required_params") or [])
        if str(param).strip()
    }
    shortest: list[str] | None = None
    for name in candidates:
        contract = contracts.get(name) or {}
        missing = [
            str(flt)
            for flt in (contract.get("required_filters") or [])
            if str(flt).strip().casefold() not in known
        ]
        if not missing:
            return []
        if shortest is None or len(missing) < len(shortest):
            shortest = missing
    return shortest or []


def _off_vocabulary(step: dict[str, Any]) -> str:
    """Система и операция должны быть из контрактов, иначе шаг неисполним."""
    from app.services.local_mcp import contract_vocabulary
    from app.services.workflow_tool_routing import normalize_operation

    vocab = contract_vocabulary()
    system = str(step.get("system") or "").strip().casefold()
    operation = normalize_operation(str(step.get("operation") or ""))
    known_systems = {str(item).casefold() for item in vocab["systems"]}
    known_operations = {str(item).casefold() for item in vocab["operations"]}
    if system not in known_systems:
        return f"системы «{step.get('system')}» нет в словаре контрактов."
    if operation not in known_operations:
        return f"операции «{step.get('operation')}» нет в словаре контрактов."
    return ""


def validate_draft(
    draft: dict[str, Any],
    *,
    allow_web: bool = False,
    materials: str = "",
) -> DraftValidation:
    """Проверить черновик до прогона. Инструменты уже должны быть подобраны."""
    issues: list[DraftIssue] = []
    if not draft or not (draft.get("steps") or []):
        issues.append(
            DraftIssue(
                kind=KIND_CONFIG_ERROR,
                message="Черновик инструкции пуст: нет ни одного шага.",
            )
        )
        return DraftValidation(issues=issues)

    if not str(draft.get("goal") or "").strip():
        issues.append(DraftIssue(kind=KIND_AMBIGUOUS, message="Не сформулирована цель агента."))

    for item in draft.get("required_clarifications") or []:
        if isinstance(item, str):
            question, options, why = item.strip(), [], ""
        elif isinstance(item, dict):
            question = str(item.get("question") or "").strip()
            options = [str(opt).strip() for opt in (item.get("options") or []) if str(opt).strip()]
            why = str(item.get("why") or "").strip()
        else:
            continue
        if not question:
            continue
        if len(options) < 2:
            issues.append(
                DraftIssue(
                    kind=KIND_AMBIGUOUS,
                    message=f"Уточнение «{question}»: нет вариантов ответа.",
                    detail="Варианты пишет Cursor-проектировщик, не backend.",
                )
            )
            continue
        issues.append(
            DraftIssue(
                kind=KIND_CLARIFY,
                message=question,
                detail=why,
                options=options[:4],
            )
        )

    if _needs_when_to_run_question(draft, materials):
        issues.append(
            DraftIssue(
                kind=KIND_CLARIFY,
                message=WHEN_TO_RUN_QUESTION,
                detail=WHEN_TO_RUN_WHY,
                options=list(WHEN_TO_RUN_OPTIONS),
            )
        )

    if not str(draft.get("recipient") or "").strip():
        issues.append(
            DraftIssue(
                kind=KIND_AMBIGUOUS,
                message="Не указан получатель результата.",
                detail="Заполни recipient или добавь уточнение с вариантами ответа.",
            )
        )

    offered: set[str] = set()
    draft_inputs = {
        str(item).strip().casefold()
        for item in (draft.get("inputs") or [])
        if str(item).strip()
    }
    for index, step in enumerate(draft.get("steps") or [], start=1):
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or f"s{index}")
        title = str(step.get("title") or step_id)

        if not step.get("system") or not step.get("operation"):
            issues.append(
                DraftIssue(
                    kind=KIND_AMBIGUOUS,
                    step_id=step_id,
                    message=f"Шаг «{title}»: не указана система или операция.",
                )
            )
            continue

        off_vocabulary = _off_vocabulary(step)
        if off_vocabulary:
            issues.append(
                DraftIssue(
                    kind=KIND_CONFIG_ERROR,
                    step_id=step_id,
                    message=f"Шаг «{title}»: {off_vocabulary}",
                    detail="Возьми system, entity и operation из словаря контрактов.",
                )
            )
            continue

        candidates = list(step.get("tool_candidates") or [])
        if not candidates:
            issues.append(
                DraftIssue(
                    kind=KIND_CONFIG_ERROR,
                    step_id=step_id,
                    message=f"Шаг «{title}»: нет инструмента для {step.get('system')}"
                    f"·{step.get('entity') or '—'}·{step.get('operation')}.",
                    detail="Инструмент с такой системой, сущностью и операцией не зарегистрирован.",
                )
            )
        else:
            missing = _missing_params(step, candidates)
            if missing:
                issues.append(
                    DraftIssue(
                        kind=KIND_CONFIG_ERROR,
                        step_id=step_id,
                        message=f"Шаг «{title}»: не хватает параметров для вызова.",
                        detail="Нужны: " + ", ".join(missing),
                    )
                )
            gaps = [
                param
                for param in _ref_params_of(step, candidates)
                if param.casefold() not in offered and param.casefold() not in draft_inputs
            ]
            if gaps:
                issues.append(
                    DraftIssue(
                        kind=KIND_CONFIG_ERROR,
                        step_id=step_id,
                        message=f"Шаг «{title}»: неоткуда взять {', '.join(gaps)}.",
                        detail=_handoff_hint(gaps),
                    )
                )

        provides = _string_list(step.get("provides")) or _default_provides(
            [str(name) for name in candidates if str(name).strip()]
        )
        offered.update(_expand_provided(provides))

        if not str(step.get("done_when") or "").strip():
            issues.append(
                DraftIssue(
                    kind=KIND_AMBIGUOUS,
                    step_id=step_id,
                    message=f"Шаг «{title}»: не сказано, когда он считается выполненным.",
                )
            )
        if not str(step.get("on_empty") or "").strip():
            issues.append(
                DraftIssue(
                    kind=KIND_AMBIGUOUS,
                    step_id=step_id,
                    message=f"Шаг «{title}»: не описано поведение при пустом ответе.",
                )
            )

    return DraftValidation(issues=issues)


def _needs_when_to_run_question(draft: dict[str, Any], materials: str) -> bool:
    answers = str((draft or {}).get("answers") or "")
    decided = str((draft or {}).get("when_to_run") or "")
    if not (materials or "").strip() and not answers.strip() and not decided.strip():
        return False
    if already_asks_when_to_run(draft):
        return False
    return not explicit_when_to_run(materials, answers, decided)


def issues_to_questions(issues: list[DraftIssue]) -> list[OpenQuestion]:
    """Только clarify с вариантами Cursor уходит человеку. Варианты сами не придумываем."""
    questions: list[OpenQuestion] = []
    for index, issue in enumerate(issues, start=1):
        if issue.kind != KIND_CLARIFY:
            continue
        questions.append(
            OpenQuestion(
                id=f"draft-q{index}",
                question=issue.message,
                why=issue.detail or "В регламенте этот бизнес-параметр не определён.",
                options=list(issue.options),
            )
        )
    return questions
