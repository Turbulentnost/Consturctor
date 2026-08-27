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
    DraftIssue,
    attach_tool_candidates,
    issues_to_questions,
    validate_draft,
)
from app.services.workflows.service import (
    PhaseResult,
    WorkflowError,
    _blocked_before_demo_report,
    _demo_validation_report,
    _merge_preserved_run_inputs,
    _needs_draft_repair,
    _require_verified_playbook,
    plan_workflow,
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


def test_project_read_uses_turboproject_not_onec_cards() -> None:
    from app.services.local_mcp import contract_vocabulary

    combos = {
        (item["system"], item["entity"], item["operation"])
        for item in contract_vocabulary()["combinations"]
    }
    assert ("turboproject", "project", "search") in combos
    assert ("turboproject", "project", "read") in combos
    assert ("turboproject", "project", "list") in combos
    assert ("constructor", "subordinate", "list") in combos

    people = select_candidates(
        {"system": "constructor", "entity": "подчинённые", "operation": "list"}
    )
    assert people == ["users.subordinates"]

    turbo = select_candidates(
        {"system": "turboproject", "entity": "project", "operation": "read"}
    )
    assert turbo == ["turboproject"]

    remapped = select_candidates(
        {"system": "onec", "entity": "проект", "operation": "read"}
    )
    assert remapped == ["turboproject"]
    assert "onec.get_document_card" not in remapped
    assert "onec.get_task_card" not in remapped

    document = select_candidates(
        {"system": "onec", "entity": "document", "operation": "read"}
    )
    assert "onec.get_document_card" in document
    assert "turboproject" not in document

    notes = select_candidates(
        {"system": "onec", "entity": "служебная записка", "operation": "search"}
    )
    assert notes[0] == "onec.meeting_service_notes"

    export = select_candidates(
        {"system": "desktop", "entity": "spreadsheet", "operation": "export"}
    )
    assert export == ["excel.create_workbook"]
    assert "excel.edit_workbook" not in export

    update = select_candidates(
        {"system": "desktop", "entity": "spreadsheet", "operation": "правка"}
    )
    assert update == ["excel.edit_workbook"]

    calendar_write = select_candidates(
        {"system": "outlook", "entity": "calendar_event", "operation": "create"}
    )
    assert calendar_write == ["outlook.create_event"]
    assert "outlook.read_calendar" not in calendar_write


def _full_step(step_id: str, **overrides) -> dict:
    step = {
        "id": step_id,
        "title": step_id,
        "required": True,
        "required_params": [],
        "data_expectation": "данные",
        "done_when": "готово",
        "on_empty": "пусто",
        "on_error": "повторить",
    }
    step.update(overrides)
    return step


def test_notify_after_project_needs_user_step() -> None:
    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s1",
                title="Проекты",
                system="turboproject",
                entity="project",
                operation="read",
            ),
            _full_step(
                "s2",
                title="Уведомить",
                system="constructor",
                entity="notification",
                operation="notify",
                required_params=["title", "user_id"],
            ),
        )
    )

    assert draft["steps"][0]["provides"] == ["projects"]
    assert draft["steps"][1]["needs_from"] == []
    messages = [issue.message for issue in validate_draft(draft).config_errors]
    assert any("user_id" in message for message in messages)


def test_project_user_notify_handoff() -> None:
    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s1",
                title="Проекты",
                system="turboproject",
                entity="project",
                operation="read",
            ),
            _full_step(
                "s2",
                title="Кто я",
                system="constructor",
                entity="user",
                operation="read",
            ),
            _full_step(
                "s3",
                title="Уведомить",
                system="constructor",
                entity="notification",
                operation="notify",
                required_params=["title", "user_id"],
            ),
        )
    )

    assert draft["steps"][1]["provides"] == ["user"]
    assert draft["steps"][2]["needs_from"] == [
        {"step": "s2", "field": "user_id", "as": "user_id"}
    ]
    assert not any("user_id" in issue.message for issue in validate_draft(draft).config_errors)
    from app.services.workflows.cursor_tools import step_candidates_block

    block = step_candidates_block(draft)
    assert "user_id ← s2.user_id" in block
    assert "отдаёт дальше: projects" in block


def test_project_does_not_provide_task_ref() -> None:
    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s1",
                title="Проекты",
                system="turboproject",
                entity="project",
                operation="read",
            ),
            _full_step(
                "s2",
                title="Карточка задачи",
                system="onec",
                entity="task",
                operation="read",
                required_params=["task_ref"],
            ),
        )
    )

    messages = [issue.message for issue in validate_draft(draft).config_errors]
    assert any("task_ref" in message for message in messages)
    assert draft["steps"][1]["needs_from"] == []


def test_operation_synonym_resolves_to_contract() -> None:
    names = select_candidates(
        _onec_step(operation="fetch", entity="task", required_params=["task_ref"])
    )

    assert names == ["onec.get_task_card"]


def test_config_error_is_draft_repair_candidate() -> None:
    validation = validate_draft(
        attach_tool_candidates(_draft(_onec_step(system="missing", entity="unknown", operation="list")))
    )

    assert validation.config_errors
    assert _needs_draft_repair(validation)


def test_blocked_before_demo_report_marks_demo_not_started() -> None:
    validation = validate_draft(
        attach_tool_candidates(_draft(_onec_step(system="missing", entity="unknown", operation="list")))
    )

    report = _blocked_before_demo_report(validation)

    assert report["status"] == "blocked_before_demo"
    assert report["demo_started"] is False
    assert report["can_run_demo"] is False
    assert report["issues"]


def test_plan_workflow_starts_demo_when_draft_ready(monkeypatch) -> None:
    class Row:
        phase = "designed"
        local_run = {"validation": {"can_run_demo": True, "status": "draft_ready"}}

    seen: dict[str, str] = {}

    def fake_design(db, *, user_id: str, workflow_id: str, on_event=None):
        del db, on_event
        seen["design"] = f"{user_id}:{workflow_id}"
        return "designed"

    def fake_demo(db, *, user_id: str, workflow_id: str, on_event=None):
        del db, on_event
        seen["demo"] = f"{user_id}:{workflow_id}"
        return "demoed"

    monkeypatch.setattr("app.services.workflows.service.design_workflow", fake_design)
    monkeypatch.setattr("app.services.workflows.service._get_owned", lambda *a, **k: Row())
    monkeypatch.setattr("app.services.workflows.service.draft_of", lambda _row: {"steps": [{"id": "s1"}]})
    monkeypatch.setattr("app.services.workflows.service.demo_workflow", fake_demo)

    assert plan_workflow(object(), user_id="u1", workflow_id="w1") == "demoed"
    assert seen == {"design": "u1:w1", "demo": "u1:w1"}


def test_plan_workflow_skips_demo_when_draft_blocked(monkeypatch) -> None:
    class Row:
        phase = "designed"
        local_run = {"validation": {"can_run_demo": False, "status": "blocked_before_demo"}}

    called = {"demo": False}

    monkeypatch.setattr(
        "app.services.workflows.service.design_workflow",
        lambda *_args, **_kwargs: "designed",
    )
    monkeypatch.setattr("app.services.workflows.service._get_owned", lambda *a, **k: Row())
    monkeypatch.setattr("app.services.workflows.service.draft_of", lambda _row: {"steps": [{"id": "s1"}]})
    monkeypatch.setattr(
        "app.services.workflows.service.demo_workflow",
        lambda **_kwargs: called.__setitem__("demo", True) or "demoed",
    )

    assert plan_workflow(object(), user_id="u1", workflow_id="w1") == "designed"
    assert called["demo"] is False


# --- preflight -----------------------------------------------------------


def test_valid_draft_has_no_issues() -> None:
    validation = validate_draft(attach_tool_candidates(_draft()))

    assert validation.ok


def test_missing_schedule_in_materials_is_clarify() -> None:
    from app.services.workflows.schedule_draft import WHEN_TO_RUN_QUESTION

    validation = validate_draft(
        attach_tool_candidates(_draft()),
        materials="контролирует сроки, качество и риски проектов. Не допускать нарушения SLA.",
    )

    assert any(issue.message == WHEN_TO_RUN_QUESTION for issue in validation.clarifications)


def test_explicit_schedule_in_materials_skips_when_question() -> None:
    from app.services.workflows.schedule_draft import WHEN_TO_RUN_QUESTION

    validation = validate_draft(
        attach_tool_candidates(_draft()),
        materials="Триггер: каждые 15 минут. Сводка руководителю.",
    )

    assert all(issue.message != WHEN_TO_RUN_QUESTION for issue in validation.clarifications)
    assert validation.ok


def test_event_trigger_in_materials_skips_when_question() -> None:
    from app.services.workflows.schedule_draft import WHEN_TO_RUN_QUESTION

    validation = validate_draft(
        attach_tool_candidates(_draft()),
        materials=(
            "В паспорте указан событийный триггер: событие вместо расписания. "
            "Агент запускается при смене статуса этапа или нарушении SLA."
        ),
    )

    assert all(issue.message != WHEN_TO_RUN_QUESTION for issue in validation.clarifications)


def test_missing_business_param_is_clarify() -> None:
    draft = _draft()
    draft["required_clarifications"] = [
        {
            "question": "За какой период строить отчёт?",
            "options": ["Текущий месяц", "Последние 30 дней", "Укажу даты"],
        }
    ]

    validation = validate_draft(attach_tool_candidates(draft))

    assert [issue.kind for issue in validation.issues] == [KIND_CLARIFY]
    assert not validation.config_errors
    assert validation.issues[0].options == ["Текущий месяц", "Последние 30 дней", "Укажу даты"]


def test_clarification_without_options_is_ambiguous() -> None:
    draft = _draft()
    draft["required_clarifications"] = ["За какой период строить отчёт?"]

    kinds = [issue.kind for issue in validate_draft(attach_tool_candidates(draft)).issues]

    assert kinds == [KIND_AMBIGUOUS]


def test_issues_to_questions_keep_cursor_options() -> None:
    options = ["Текущий месяц, SLA 7 дней", "Последние 30 дней, SLA 3 дня"]
    questions = issues_to_questions(
        [DraftIssue(kind=KIND_CLARIFY, message="Период и горизонт SLA", options=options)]
    )

    assert questions[0].options == options


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


def test_next_step_input_names_do_not_fail_current_result() -> None:
    document = {
        "id": "s7",
        "system": "onec",
        "entity": "document",
        "operation": "read",
        "tool_candidates": ["onec.get_document_card"],
        "required_params": ["document_ref"],
    }
    task = {
        "id": "s8",
        "system": "onec",
        "entity": "task",
        "operation": "read",
        "required_params": ["task_ref"],
    }
    notify = {
        "id": "s9",
        "system": "constructor",
        "entity": "notification",
        "operation": "notify",
        "required_params": ["title", "user_id"],
    }
    card = evaluate_tool_result(
        step=document,
        name="onec.get_document_card",
        arguments={"document_ref": "doc-1"},
        result={"document": {"ref": "doc-1", "number": "0001"}},
        next_step=task,
    )
    assert card.data_status == "complete"
    assert card.accepted
    task_card = evaluate_tool_result(
        step=task,
        name="onec.get_task_card",
        arguments={"task_ref": "task-1"},
        result={"task": {"ref": "task-1", "name": "Согласовать"}},
        next_step=notify,
    )
    assert task_card.data_status == "complete"
    assert task_card.accepted


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


def test_com_timeout_error_asks_to_retry_same_call() -> None:
    step = {
        "id": "s2",
        "system": "onec",
        "entity": "service_note",
        "operation": "search",
        "tool_candidates": ["onec.meeting_service_notes"],
    }
    timed_out = evaluate_tool_result(
        step=step,
        name="onec.meeting_service_notes",
        arguments={"date": "2026-08-20"},
        result={
            "error": (
                "Command '['C:\\\\Windows\\\\SysWOW64\\\\cscript.exe', '//Nologo']' "
                "timed out after 150 seconds"
            )
        },
    )
    assert timed_out.data_status == "mismatch"
    assert "повтори" in timed_out.next_action.casefold()
    assert "исправь" not in timed_out.next_action.casefold()
    human = evaluate_tool_result(
        step=step,
        name="onec.meeting_service_notes",
        arguments={"date": "2026-08-20"},
        result={"error": "1С не ответила через COM за 180 с. Повтори тот же вызов."},
    )
    assert "повтори" in human.next_action.casefold()


def test_turboproject_read_is_complete_even_if_step_said_onec() -> None:
    step = {
        "id": "s1",
        "system": "onec",
        "entity": "project",
        "operation": "read",
        "tool_candidates": ["turboproject"],
    }
    verdict = evaluate_tool_result(
        step=step,
        name="turboproject",
        arguments={"limit": 20},
        result={"projects": [{"id": "p1", "name": "Реконструкция"}], "count": 1},
    )

    assert verdict.data_status == "complete"
    assert verdict.accepted


def test_document_card_stays_rejected_for_project_step() -> None:
    step = {
        "id": "s1",
        "system": "onec",
        "entity": "project",
        "operation": "read",
        "tool_candidates": ["turboproject"],
    }
    verdict = evaluate_tool_result(
        step=step,
        name="onec.get_document_card",
        arguments={"document_ref": "doc-1"},
        result={"document": {"ref": "doc-1"}},
    )

    assert verdict.data_status == "mismatch"
    assert not verdict.accepted


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


def test_ledger_blocks_step_until_needs_from_are_closed() -> None:
    from app.services.workflows.cursor_tools import _followup_prompt, _reject_blocked_handoff

    draft = attach_tool_candidates(
        {
            "status": "draft",
            "steps": [
                _full_step(
                    "s1",
                    system="onec",
                    entity="service_note",
                    operation="search",
                    provides=["notes"],
                ),
                _full_step(
                    "s2",
                    system="outlook",
                    entity="calendar_event",
                    operation="list",
                    provides=["events"],
                    needs_from=[{"step": "s1", "field": "notes", "as": "series_window"}],
                ),
                _full_step(
                    "s3",
                    system="desktop",
                    entity="spreadsheet",
                    operation="export",
                    provides=["file"],
                    required_params=["filename"],
                    needs_from=[{"step": "s2", "field": "events", "as": "calendar_events"}],
                ),
            ],
        }
    )
    ledger = StepLedger(draft)
    outlook = ledger.step_by_id("s2")
    export = ledger.step_by_id("s3")

    assert ledger.open_required_tools() == ["onec.meeting_service_notes"]
    assert ledger.unmet_needs(outlook) == ["s1"]
    assert "s1" in _reject_blocked_handoff(ledger, outlook)
    assert "excel.create_workbook" in (export.get("tool_candidates") or [])
    assert "excel.edit_workbook" not in (export.get("tool_candidates") or [])

    text = _followup_prompt(
        [{"name": "notify.send", "ok": True}],
        mode="execute",
        pending=None,
        steps_left=ledger.missing_required(),
    )
    assert "обязательные шаги" in text
    assert "constructor_tool" in text
    assert "RESULT" not in text or "не пиши" in text


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
    assert report["demo_started"] is True
    assert report["can_run_demo"] is True
    assert report["status"] == "demo_failed"


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


def test_parse_playbook_draft_keeps_run_inputs() -> None:
    draft = prompts.parse_playbook_draft(
        """
        {
          "goal": "собрать план",
          "run_inputs": [
            {"name": "grafik.xlsx", "description": "obrazec", "accept": ".xlsx"},
            "grafik.xlsx"
          ],
          "steps": [{"id": "s1", "title": "Прочитать файл", "system": "desktop", "entity": "spreadsheet", "operation": "read"}]
        }
        """
    )
    assert [item["name"] for item in draft["run_inputs"]] == ["grafik.xlsx"]
    assert draft["run_inputs"][0]["accept"] == ".xlsx"


def test_merge_preserved_run_inputs_keeps_sidecar_list() -> None:
    parsed = prompts.parse_playbook_draft('{"goal": "x", "steps": []}')
    assert parsed["run_inputs"] == []
    merged = _merge_preserved_run_inputs(
        parsed,
        {"playbook_draft": {"run_inputs": [{"name": "grafik.xlsx", "accept": ".xlsx"}]}},
    )
    assert merged["run_inputs"][0]["name"] == "grafik.xlsx"
    already = _merge_preserved_run_inputs(
        {"run_inputs": [{"name": "from-json.xlsx"}]},
        {"playbook_draft": {"run_inputs": [{"name": "old.xlsx"}]}},
    )
    assert already["run_inputs"][0]["name"] == "from-json.xlsx"


def test_draft_schema_includes_run_inputs() -> None:
    prompt = prompts.build_playbook_draft_prompt(document_text="регламент", title="Агент")
    assert "run_inputs" in prompt


def test_draft_prompt_asks_for_json_only_without_transport_lecture() -> None:
    prompt = prompts.build_playbook_draft_prompt(document_text="регламент", title="Агент")

    # Транспорт вызова прикладывает фаза, проектировщик про него не рассуждает.
    assert "constructor_tool" not in prompt
    assert "вернуть JSON черновика" in prompt
    assert "не решай" in prompt.casefold()
    assert "додумывать логику" in prompt
    assert "service_note" in prompt
    assert "6.4" in prompt


def test_draft_prompt_interactive_asks_gaps_before_json() -> None:
    prompt = prompts.build_playbook_draft_prompt(
        document_text="регламент",
        title="Агент",
        interactive=True,
    )

    assert "askQuestion" in prompt
    assert "после закрытых пробелов" in prompt
    assert "период, объём, получатель" not in prompt
    assert "единственная задача" not in prompt


def test_draft_prompt_carries_contract_vocabulary() -> None:
    from app.services.workflows.cursor_tools import contract_vocabulary_block

    prompt = prompts.build_playbook_draft_prompt(
        document_text="регламент",
        title="Агент",
        vocabulary=contract_vocabulary_block(),
    )

    assert "СЛОВАРЬ КОНТРАКТОВ" in prompt
    assert "из допустимых сочетаний" in prompt
    assert "turboproject · project · read" in prompt
    assert "не карточка документа" in prompt


def test_design_phase_block_offers_only_context_tools() -> None:
    from app.services.local_mcp import DESIGN_PHASE, design_context_tools
    from app.services.workflows.cursor_tools import tools_prompt_block

    block = tools_prompt_block(phase=DESIGN_PHASE)
    allowed = {str(tool.get("name")) for tool in design_context_tools()}

    assert allowed
    for name in allowed:
        assert name in block
    # Бизнес-инструменты на проектировании не предлагаем.
    assert "onec.sql_query" not in block
    assert "turboproject" not in block


def test_design_phase_rejects_business_tool() -> None:
    from app.services.local_mcp import DESIGN_PHASE
    from app.services.workflows.cursor_tools import _reject_off_phase

    assert _reject_off_phase(DESIGN_PHASE, "onec.sql_query")
    assert _reject_off_phase(DESIGN_PHASE, "users.current") == ""
    assert _reject_off_phase(DESIGN_PHASE, "users.subordinates") == ""
    assert _reject_off_phase("execute", "onec.sql_query") == ""


def test_execute_block_scopes_tools_to_step_candidates() -> None:
    from app.services.workflows.cursor_tools import tools_prompt_block

    draft = attach_tool_candidates(_draft())
    block = tools_prompt_block(draft=draft)

    assert "s1" in block
    assert "onec.erp_tasks_period" in block
    assert "data.process" in block
    assert "constructor · dataset · execute" in block
    # Полный каталог в промпт исполнителя не попадает.
    assert "excel.create_workbook" not in block


def test_step_outside_vocabulary_is_config_error() -> None:
    draft = attach_tool_candidates(_draft(_onec_step(system="megacrm", operation="list")))

    validation = validate_draft(draft)

    assert validation.config_errors
    assert "словаре контрактов" in validation.config_errors[0].message


def test_unknown_operation_is_config_error() -> None:
    draft = attach_tool_candidates(_draft(_onec_step(operation="teleport")))

    validation = validate_draft(draft)

    assert validation.config_errors


def test_stream_delta_merges_overlapping_window() -> None:
    from app.services.workflows.service import stream_delta

    assert stream_delta("ABCD", "CDEF") == "EF"
    assert stream_delta("ABCD", "ABCDEF") == "EF"
    assert stream_delta("", "ABCD") == "ABCD"
    assert stream_delta("ABCD", "BC") == ""
    assert stream_delta("ABCD", "XY") == "XY"


def test_helper_is_not_off_contract() -> None:
    from app.services.workflows.cursor_tools import _reject_off_contract

    step = {"id": "s1", "system": "onec", "entity": "task", "operation": "list", "tool_candidates": ["onec.erp_tasks_period"]}

    assert _reject_off_contract(step, "data.process") == ""
    assert _reject_off_contract(step, "excel.create_workbook")


def test_helper_does_not_overwrite_excel_step() -> None:
    from app.services.workflows.cursor_tools import StepLedger

    draft = attach_tool_candidates(
        {
            "status": "draft",
            "steps": [
                _full_step(
                    "s6",
                    system="desktop",
                    entity="spreadsheet",
                    operation="export",
                    required_params=["filename"],
                    provides=["file"],
                    on_empty="не создавать пустой файл",
                )
            ],
        }
    )
    ledger = StepLedger(draft)
    step = ledger.step_by_id("s6")
    good = evaluate_tool_result(
        step=step,
        name="excel.create_workbook",
        arguments={"filename": "kalendar.xlsx"},
        result={"path": r"C:\tmp\kalendar.xlsx", "filename": "kalendar.xlsx"},
    )
    ledger.record(step=step, name="excel.create_workbook", verdict=good)
    helper = evaluate_tool_result(
        step=step,
        name="data.process",
        arguments={"code": "result = 1"},
        result={"result": 1},
    )
    ledger.record(step=step, name="data.process", verdict=helper)

    assert good.accepted
    assert helper.accepted
    assert ledger.as_list()[0]["tool"] == "excel.create_workbook"
    assert ledger.as_list()[0]["status"] == "completed"
    assert ledger.missing_required() == []
    assert ledger.resolve({"name": "data.process", "step": "s6"}) is None


def test_calendar_create_gets_export_file_step() -> None:
    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s4",
                system="outlook",
                entity="calendar_event",
                operation="list",
            ),
            _full_step(
                "s6",
                system="outlook",
                entity="calendar_event",
                operation="create",
                required_params=["subject", "start"],
            ),
            _full_step(
                "s7",
                system="constructor",
                entity="notification",
                operation="notify",
                required_params=["title", "user_id"],
            ),
        )
    )
    ids = [str(step.get("id") or "") for step in draft["steps"]]
    ops = [str(step.get("operation") or "") for step in draft["steps"]]
    export = [step for step in draft["steps"] if step.get("operation") == "export"]
    assert len(export) == 1
    assert export[0]["system"] == "desktop"
    assert export[0]["tool_candidates"] == ["excel.create_workbook"]
    assert ids.index(str(export[0]["id"])) < ids.index("s7")
    assert ops.count("list") >= 2
    assert ops.index("list") < ops.index("create")
    assert ops[ops.index("create") + 1] == "list"


def test_calendar_create_inserts_list_before_and_after() -> None:
    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s6",
                system="outlook",
                entity="calendar_event",
                operation="create",
                required_params=["subject", "start"],
            )
        )
    )
    ops = [str(step.get("operation") or "") for step in draft["steps"]]
    assert ops[0] == "list"
    assert "create" in ops
    assert ops[ops.index("create") + 1] == "list"
    assert "outlook.read_calendar" in draft["steps"][0]["tool_candidates"]


def test_read_calendar_is_companion_on_create_step() -> None:
    from app.services.workflows.cursor_tools import _reject_off_contract

    step = {
        "id": "s6",
        "system": "outlook",
        "entity": "calendar_event",
        "operation": "create",
        "tool_candidates": ["outlook.create_event"],
    }
    assert _reject_off_contract(step, "outlook.read_calendar") == ""
    assert _reject_off_contract(step, "excel.create_workbook")


def test_calendar_create_does_not_duplicate_existing_export() -> None:
    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s6",
                system="outlook",
                entity="calendar_event",
                operation="create",
                required_params=["subject", "start"],
            ),
            _full_step(
                "s7",
                system="desktop",
                entity="spreadsheet",
                operation="export",
                required_params=["filename"],
            ),
        )
    )
    exports = [step for step in draft["steps"] if step.get("operation") == "export"]
    assert len(exports) == 1
    assert exports[0]["id"] == "s7"
    ops = [str(step.get("operation") or "") for step in draft["steps"]]
    assert ops.count("list") >= 2


def test_verify_list_empty_after_create_is_mismatch() -> None:
    from app.services.workflows.tool_result_validation import evaluate_tool_result

    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s6",
                system="outlook",
                entity="calendar_event",
                operation="create",
                required_params=["subject", "start"],
            )
        )
    )
    verify = next(
        step
        for step in draft["steps"]
        if step.get("operation") == "list" and "нов" in str(step.get("done_when") or "")
    )
    verdict = evaluate_tool_result(
        step=verify,
        name="outlook.read_calendar",
        arguments={"days_forward": 365},
        result={"events": [], "count": 0, "free_slots": []},
    )
    assert not verdict.accepted
    assert verdict.data_status == "mismatch"


def test_closed_calendar_step_skips_second_invoke() -> None:
    from app.services.workflows.cursor_tools import StepLedger

    draft = attach_tool_candidates(
        _draft(
            _full_step(
                "s4",
                system="outlook",
                entity="calendar_event",
                operation="list",
            ),
            _full_step(
                "s5",
                system="constructor",
                entity="user",
                operation="list",
            ),
        )
    )
    ledger = StepLedger(draft)
    step = ledger.step_by_id("s4")
    good = evaluate_tool_result(
        step=step,
        name="outlook.read_calendar",
        arguments={"date_from": "2026-08-20"},
        result={"events": [{"subject": "планёрка"}], "count": 1, "free_slots": []},
    )
    ledger.record(step=step, name="outlook.read_calendar", verdict=good)
    ledger.record(
        step=step,
        name="outlook.read_calendar",
        verdict=None,
        error="COM worker не ответил за 30 секунд",
    )

    resolved = ledger.resolve({"name": "outlook.read_calendar", "step": "s4"})
    assert good.accepted
    assert ledger.as_list()[0]["status"] == "completed"
    assert ledger.should_skip_invoke("outlook.read_calendar", resolved)
    assert not ledger.should_skip_invoke(
        "users.list", ledger.resolve({"name": "users.list"})
    )


def test_empty_valid_stop_skips_later_writes() -> None:
    from app.services.workflows.cursor_tools import StepLedger

    draft = attach_tool_candidates(
        {
            "status": "draft",
            "steps": [
                _full_step(
                    "s2",
                    system="onec",
                    entity="service_note",
                    operation="search",
                    provides=["notes"],
                    on_empty="завершить без календаря: подходящих СЗ нет, записи не выполнять",
                ),
                _full_step(
                    "s6",
                    system="outlook",
                    entity="calendar_event",
                    operation="create",
                    provides=["event"],
                    required_params=["subject", "start"],
                    needs_from=[{"step": "s2", "field": "notes", "as": "notes"}],
                ),
            ],
        }
    )
    ledger = StepLedger(draft)
    search = ledger.step_by_id("s2")
    empty = evaluate_tool_result(
        step=search,
        name="onec.meeting_service_notes",
        arguments={"date": "2026-08-20"},
        result={"notes": [], "count": 0},
    )
    ledger.record(step=search, name="onec.meeting_service_notes", verdict=empty)

    assert empty.data_status == "empty_valid"
    assert ledger.as_list()[1]["status"] == "skipped"
    assert ledger.missing_required() == []


def test_contract_vocabulary_skips_helper() -> None:
    from app.services.local_mcp import contract_vocabulary, helper_tools

    helpers = helper_tools()
    assert helpers
    vocab = contract_vocabulary()
    assert not any(item["entity"] == "dataset" for item in vocab["combinations"])


def test_validation_rules_ask_where_to_look() -> None:
    assert "где в предметной области" in prompts._VALIDATION_RULES
    assert "FAILED_VALIDATION" in prompts._VALIDATION_RULES


def test_packed_result_keeps_dataset_id() -> None:
    from app.services.workflows.cursor_tools import DatasetRegistry

    registry = DatasetRegistry()
    packed = registry.pack({"document": {"title": "x" * 9000}}, limit=200)

    assert packed["truncated"] is True
    assert packed["dataset_id"] == "d1"
    assert "document" in packed["shape"]["keys"]
    assert registry.get("d1")["document"]["title"].startswith("x")
