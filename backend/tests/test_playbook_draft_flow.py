from __future__ import annotations

import json

import pytest

from app.models.workflow import Workflow
from app.services.workflow_tool_routing import regulation_allows_web, select_candidates
from app.services.workflows import prompts
from app.services.workflows.cursor_tools import StepLedger, extract_tool_calls
from app.services.workflows.playbook_validation import (
    KIND_AMBIGUOUS,
    KIND_CLARIFY,
    KIND_CONFIG_ERROR,
    attach_tool_candidates,
    validate_draft,
)
from app.services.workflows.service import (
    PhaseResult,
    WorkflowError,
    _demo_validation_report,
    _require_verified_playbook,
)
from app.services.workflows.tool_result_validation import evaluate_tool_result


def _onec_step(**overrides) -> dict:
    step = {
        "id": "s1",
        "title": "Собрать задачи за период",
        "required": True,
        "system": "onec",
        "entity": "task",
        "operation": "list",
        "required_params": ["date_from", "date_to"],
        "data_expectation": "список задач с исполнителем и сроком",
        "done_when": "получены задачи за весь период",
        "on_empty": "сообщить, что задач нет",
        "on_error": "повторить с другими параметрами",
    }
    step.update(overrides)
    return step


def _draft(*steps: dict) -> dict:
    return {
        "status": "draft",
        "goal": "Отчёт по задачам",
        "inputs": ["период"],
        "required_clarifications": [],
        "result": "таблица задач",
        "recipient": "руководитель",
        "confirmation_points": [],
        "steps": list(steps) or [_onec_step()],
    }


# --- подбор инструментов -------------------------------------------------


def test_onec_step_never_gets_web_tools() -> None:
    names = select_candidates(_onec_step())

    assert names
    assert all(name.startswith("onec.") for name in names)
    assert "web_search" not in names
    assert "site_browser" not in names


def test_web_step_keeps_web_tools_when_regulation_allows() -> None:
    step = {"system": "web", "entity": "web_page", "operation": "search", "required_params": ["query"]}

    names = select_candidates(step, allow_web=True)

    assert "web_search" in names


def test_regulation_allows_web_only_on_explicit_hint() -> None:
    assert regulation_allows_web("Забрать данные с сайта поставщика")
    assert not regulation_allows_web("Собрать задачи из 1С за месяц")


def test_unknown_entity_and_operation_leave_no_candidates() -> None:
    assert select_candidates(_onec_step(entity="unicorn", operation="teleport")) == []


def test_operation_synonym_resolves_to_contract() -> None:
    names = select_candidates(
        _onec_step(operation="fetch", entity="task", required_params=["task_ref"])
    )

    assert names == ["onec.get_task_card"]


# --- preflight -----------------------------------------------------------


def test_valid_draft_has_no_issues() -> None:
    validation = validate_draft(attach_tool_candidates(_draft()))

    assert validation.ok


def test_missing_business_param_is_clarify() -> None:
    draft = _draft()
    draft["required_clarifications"] = ["За какой период строить отчёт?"]

    validation = validate_draft(attach_tool_candidates(draft))

    assert [issue.kind for issue in validation.issues] == [KIND_CLARIFY]
    assert not validation.config_errors


def test_no_compatible_tool_is_config_error() -> None:
    draft = _draft(_onec_step(entity="unicorn", operation="teleport"))

    validation = validate_draft(attach_tool_candidates(draft))

    assert validation.config_errors
    assert not validation.clarifications


def test_missing_call_params_is_config_error() -> None:
    draft = _draft(_onec_step(entity="task", operation="read", required_params=[]))

    kinds = {issue.kind for issue in validate_draft(attach_tool_candidates(draft)).issues}

    assert KIND_CONFIG_ERROR in kinds


def test_step_without_done_when_is_ambiguous() -> None:
    draft = _draft(_onec_step(done_when="", on_empty=""))

    kinds = [issue.kind for issue in validate_draft(attach_tool_candidates(draft)).issues]

    assert kinds == [KIND_AMBIGUOUS, KIND_AMBIGUOUS]


# --- вердикт по ответу инструмента ---------------------------------------


def _candidate_step() -> dict:
    return attach_tool_candidates(_draft())["steps"][0]


def test_full_answer_is_complete() -> None:
    verdict = evaluate_tool_result(
        step=_candidate_step(),
        name="onec.erp_tasks_period",
        arguments={"date_from": "2026-01-01", "date_to": "2026-01-31"},
        result={"tasks": [{"id": 1}], "count": 1},
    )

    assert verdict.data_status == "complete"
    assert verdict.accepted


def test_empty_answer_with_filters_is_empty_valid() -> None:
    verdict = evaluate_tool_result(
        step=_candidate_step(),
        name="onec.erp_tasks_period",
        arguments={"date_from": "2026-01-01", "date_to": "2026-01-31"},
        result={"tasks": []},
    )

    assert verdict.data_status == "empty_valid"
    assert verdict.accepted


def test_empty_answer_without_params_is_suspect() -> None:
    verdict = evaluate_tool_result(
        step=_candidate_step(),
        name="onec.erp_tasks_period",
        arguments={},
        result={"tasks": []},
    )

    assert verdict.data_status == "empty_suspect"
    assert not verdict.accepted


def test_unfinished_pagination_is_partial() -> None:
    verdict = evaluate_tool_result(
        step=_candidate_step(),
        name="onec.erp_tasks_period",
        arguments={"date_from": "a", "date_to": "b", "limit": 50},
        result={"tasks": [{"id": i} for i in range(50)], "count": 120},
    )

    assert verdict.data_status == "partial"
    assert not verdict.checks["pagination"]


def test_wrong_system_is_mismatch() -> None:
    verdict = evaluate_tool_result(
        step=_candidate_step(),
        name="web_search",
        arguments={"query": "задачи"},
        result={"results": [{"title": "x"}]},
    )

    assert verdict.data_status == "mismatch"


def test_tool_error_is_mismatch() -> None:
    verdict = evaluate_tool_result(
        step=_candidate_step(),
        name="onec.erp_tasks_period",
        arguments={"date_from": "a", "date_to": "b"},
        result={"error": "нет доступа"},
    )

    assert verdict.data_status == "mismatch"


# --- ledger --------------------------------------------------------------


def test_tool_call_block_carries_step_id() -> None:
    text = (
        "```constructor_tool\n"
        + json.dumps({"name": "onec.erp_tasks_period", "step": "s1", "arguments": {}})
        + "\n```"
    )

    calls = extract_tool_calls(text)

    assert calls == [{"name": "onec.erp_tasks_period", "arguments": {}, "step": "s1"}]


def test_ledger_marks_step_completed_only_on_accepted_verdict() -> None:
    ledger = StepLedger(attach_tool_candidates(_draft()))
    step = ledger.step_by_id("s1")

    partial = evaluate_tool_result(
        step=step,
        name="onec.erp_tasks_period",
        arguments={"date_from": "a", "date_to": "b", "limit": 50},
        result={"tasks": [{"id": i} for i in range(50)], "count": 120},
    )
    ledger.record(step=step, name="onec.erp_tasks_period", verdict=partial)

    assert ledger.missing_required() == ["s1"]

    good = evaluate_tool_result(
        step=step,
        name="onec.erp_tasks_period",
        arguments={"date_from": "a", "date_to": "b"},
        result={"tasks": [{"id": 1}], "count": 1},
    )
    ledger.record(step=step, name="onec.erp_tasks_period", verdict=good)

    assert ledger.missing_required() == []
    assert ledger.as_list()[0]["attempts"] == 2


# --- гейт итога ----------------------------------------------------------


def _ledger_entry(**overrides) -> dict:
    entry = {
        "id": "s1",
        "required": True,
        "status": "completed",
        "data_status": "complete",
        "tool": "onec.erp_tasks_period",
        "attempts": 1,
        "error": "",
        "reasons": [],
    }
    entry.update(overrides)
    return entry


def test_gate_passes_on_closed_ledger() -> None:
    phase = PhaseResult(text="RESULT: готово", step_ledger=[_ledger_entry()])

    report = _demo_validation_report(phase, attach_tool_candidates(_draft()))

    assert report["ok"]


def test_gate_blocks_on_unfinished_step() -> None:
    phase = PhaseResult(
        text="RESULT: готово",
        step_ledger=[_ledger_entry(status="failed", data_status="partial")],
    )

    report = _demo_validation_report(phase, attach_tool_candidates(_draft()))

    assert not report["ok"]
    assert report["unfinished"][0]["id"] == "s1"


def test_gate_blocks_on_failed_validation_marker() -> None:
    phase = PhaseResult(text="FAILED_VALIDATION: нет данных", step_ledger=[_ledger_entry()])

    report = _demo_validation_report(phase, attach_tool_candidates(_draft()))

    assert not report["ok"]
    assert report["failed_validation"]


def test_gate_blocks_when_no_step_confirmed() -> None:
    phase = PhaseResult(text="RESULT: готово", step_ledger=[])

    report = _demo_validation_report(phase, attach_tool_candidates(_draft()))

    assert not report["ok"]


# --- правка черновика и публикация ---------------------------------------


def test_refine_parser_keeps_draft_steps_when_model_omits_them() -> None:
    draft = attach_tool_candidates(_draft())
    text = json.dumps(
        {"name": "Отчёт", "instructions": "шаги", "example_run": "прогон"},
        ensure_ascii=False,
    )

    parsed = prompts.parse_playbook_refine(text, draft=draft)

    assert parsed["example_run"] == "прогон"
    assert parsed["steps"] == draft["steps"]


def test_refine_parser_takes_corrected_steps() -> None:
    draft = attach_tool_candidates(_draft())
    text = json.dumps(
        {
            "instructions": "шаги",
            "example_run": "прогон",
            "steps": [_onec_step(id="s1", title="Точный вызов onec.erp_tasks_period")],
        },
        ensure_ascii=False,
    )

    parsed = prompts.parse_playbook_refine(text, draft=draft)

    assert parsed["steps"][0]["title"] == "Точный вызов onec.erp_tasks_period"


def test_publish_rejects_draft_playbook() -> None:
    row = Workflow(
        id="w1",
        user_id="u1",
        title="Агент",
        local_run={"playbook_draft": _draft(), "validation": {"ok": False, "reasons": ["нет данных"]}},
    )

    with pytest.raises(WorkflowError):
        _require_verified_playbook(row, {"status": "draft", "instructions": "x"})


def test_publish_allows_verified_playbook() -> None:
    row = Workflow(
        id="w1",
        user_id="u1",
        title="Агент",
        local_run={
            "playbook_draft": _draft(),
            "validation": {"ok": True, "reasons": []},
            "draft_validation": {"config_error_count": 0},
        },
    )

    _require_verified_playbook(row, {"status": "verified", "instructions": "x"})


def test_draft_prompt_forbids_tool_calls() -> None:
    prompt = prompts.build_playbook_draft_prompt(document_text="регламент", title="Агент")

    assert "constructor_tool" in prompt
    assert "запрещ" in prompt
