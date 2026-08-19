from app.ui.pages.workflow_page import _stream_delta


def test_stream_delta_merges_overlapping_window() -> None:
    assert _stream_delta("ABCD", "CDEF") == "EF"
    assert _stream_delta("ABCD", "ABCDEF") == "EF"
    assert _stream_delta("", "ABCD") == "ABCD"
    assert _stream_delta("ABCD", "BC") == ""
    assert _stream_delta("ABCD", "XY") == "XY"
