"""Проверка полноты чернового playbook до запуска на живых данных.

Три класса проблем не смешиваются:
- clarify — не определён бизнес-параметр, спрашиваем человека;
- config_error — нет совместимого инструмента или параметров, это ошибка конфигурации;
- ambiguous — шаг описан неоднозначно, возвращаем проектировщику.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.services.workflow_tool_routing import select_candidates
from app.services.workflows.plan_models import OpenQuestion

KIND_CLARIFY = "clarify"
KIND_CONFIG_ERROR = "config_error"
KIND_AMBIGUOUS = "ambiguous"


@dataclass
class DraftIssue:
    kind: str
    message: str
    step_id: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "message": self.message,
            "step_id": self.step_id,
            "detail": self.detail,
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


def attach_tool_candidates(draft: dict[str, Any], *, allow_web: bool = False) -> dict[str, Any]:
    """Проставить каждому шагу инструменты, совместимые по контракту."""
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
    return {**draft, "steps": enriched}


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


def validate_draft(draft: dict[str, Any], *, allow_web: bool = False) -> DraftValidation:
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

    for question in draft.get("required_clarifications") or []:
        text = str(question).strip()
        if text:
            issues.append(DraftIssue(kind=KIND_CLARIFY, message=text))

    if not str(draft.get("recipient") or "").strip():
        issues.append(
            DraftIssue(
                kind=KIND_CLARIFY,
                message="Кому отдавать результат работы агента?",
            )
        )

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


def issues_to_questions(issues: list[DraftIssue]) -> list[OpenQuestion]:
    """Только clarify превращается в вопросы человеку."""
    questions: list[OpenQuestion] = []
    for index, issue in enumerate(issues, start=1):
        if issue.kind != KIND_CLARIFY:
            continue
        questions.append(
            OpenQuestion(
                id=f"draft-q{index}",
                question=issue.message,
                why="В регламенте этот бизнес-параметр не определён.",
            )
        )
    return questions
