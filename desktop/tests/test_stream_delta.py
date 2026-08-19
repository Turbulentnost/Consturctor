from app.ui.pages.workflow_page import _demo_already_ran_state, _stream_delta


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
