"""Autonomy level 1 fills passport scope fields — no user quiz."""

from __future__ import annotations

from app.services.agent_passport.service import (
    AgentPassport,
    _LEVEL1_CAN_AUTONOMOUS,
    _LEVEL1_FORBIDDEN,
    _LEVEL1_NEEDS_APPROVAL,
    _apply_autonomy_scope,
    _with_gaps,
    complete_passport,
)
from app.services.agent_passport.types import ExtractedFunction


def test_autonomy_scope_fills_and_skips_questions() -> None:
    passport = AgentPassport(name="Контроль сроков", goal="не срывать SLA")
    _apply_autonomy_scope(passport)
    filled = _with_gaps(passport, bp_name="Контроль", excerpt="мониторинг сроков")
    assert filled.can_autonomous == _LEVEL1_CAN_AUTONOMOUS
    assert filled.needs_human_approval == _LEVEL1_NEEDS_APPROVAL
    assert filled.forbidden.startswith(_LEVEL1_FORBIDDEN)
    assert "forbidden" not in filled.missing_fields
    assert "can_autonomous" not in filled.missing_fields
    assert "needs_human_approval" not in filled.missing_fields
    assert not any(
        str(q.get("field")) in {"forbidden", "can_autonomous", "needs_human_approval"}
        for q in filled.questions
    )


def test_complete_passport_does_not_reopen_forbidden() -> None:
    passport = AgentPassport(
        name="Контроль",
        goal="контроль",
        trigger="по событию",
        receives="статусы",
        checks="1С",
        decisions="эскалация",
        result="отчёт",
        questions=[{"field": "forbidden", "prompt": "Что нельзя?"}],
    )
    result = complete_passport(
        passport,
        answers={"forbidden": "не знаю"},
        bp_name="Контроль",
        excerpt="мониторинг",
        functions=[],
    )
    assert result.forbidden
    assert "forbidden" not in result.missing_fields
    assert not any(str(q.get("field")) == "forbidden" for q in result.questions)


def test_physical_steps_appended_to_forbidden() -> None:
    passport = AgentPassport(name="Склад")
    _apply_autonomy_scope(
        passport,
        functions=[
            ExtractedFunction(
                name="Отгрузка со склада",
                automation_kind="physical",
            )
        ],
    )
    assert "Отгрузка со склада" in passport.forbidden
