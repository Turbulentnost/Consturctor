from app.api_client import WorkflowRecord
from app.ui.pages.workflow_page import (
    _demo_already_ran_state,
    _stream_delta,
    _strip_tool_call_text,
    demo_run_passed,
)
from app.ui.widgets.cursor_feed import compact_tool_result, format_tool_detail


def test_stream_delta_merges_overlapping_window() -> None:
    assert _stream_delta("ABCD", "CDEF") == "EF"
    assert _stream_delta("ABCD", "ABCDEF") == "EF"
    assert _stream_delta("", "ABCD") == "ABCD"
    assert _stream_delta("ABCD", "BC") == ""
    assert _stream_delta("ABCD", "XY") == "XY"


def test_demo_already_ran_state_from_validation() -> None:
    assert _demo_already_ran_state({"demo_started": True, "can_run_demo": True, "ok": False})
    assert _demo_already_ran_state({"status": "demo_failed"})
    assert not _demo_already_ran_state({"demo_started": False, "can_run_demo": True, "status": "draft_ready"})
    assert not _demo_already_ran_state({})


def test_demo_run_passed_from_answer_and_flags() -> None:
    assert demo_run_passed(None, "TESTS: PASS")
    assert not demo_run_passed(None, "TESTS: FAIL")
    assert not demo_run_passed(None, "TESTS: PASS\nTESTS: FAIL")
    passed = WorkflowRecord(
        id="wf-1",
        title="A",
        phase="designed",
        last_result="The control circuit worked.\nTESTS: PASS",
    )
    assert demo_run_passed(passed)
    flagged = WorkflowRecord(
        id="wf-1",
        title="A",
        phase="designed",
        local_run={"playbook": {"demo_ok": True}},
    )
    assert demo_run_passed(flagged)
    pending = WorkflowRecord(id="wf-1", title="A", phase="designed", last_result="draft json")
    assert not demo_run_passed(pending)


def test_strip_tool_call_hides_constructor_block() -> None:
    text = (
        "Смотрю текущего пользователя.\n"
        "```constructor_tool\n"
        '{"name": "users.current", "step": "s1", "arguments": {}}\n'
        "```\n"
    )
    assert "users.current" not in _strip_tool_call_text(text)
    assert "Смотрю текущего пользователя." in _strip_tool_call_text(text)


def test_strip_tool_call_hides_bare_json() -> None:
    assert _strip_tool_call_text('{"name": "users.current", "step": "s1", "arguments": {}}') == ""


def test_format_tool_detail_shows_result_not_arguments() -> None:
    text = format_tool_detail(
        arguments={"query": "all"},
        result={"user": {"fio": "Иванов Иван"}},
    )
    assert "Иванов Иван" in text
    assert "Аргументы" not in text
    assert "query" not in text


def test_compact_tool_result_keeps_envelope_not_full_json() -> None:
    fat = {
        "summary": {"summary": "8 projects", "projects_count": 8},
        "sample": {"projects": [{"name": "A"}, {"name": "B"}]},
        "result_file": "tool_results/portfolio.json",
        "projects": [{"blob": "x" * 2000} for _ in range(8)],
        "externalized": True,
    }
    text = compact_tool_result(fat)
    assert "8 projects" in text
    assert "file: tool_results/portfolio.json" in text
    assert "x" * 100 not in text
    assert "externalized" not in text
