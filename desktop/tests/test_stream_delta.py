from app.ui.pages.workflow_page import (
    _demo_already_ran_state,
    _stream_delta,
    _strip_tool_call_text,
)
from app.ui.widgets.cursor_feed import format_tool_detail


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
