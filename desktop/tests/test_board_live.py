from app.api_client import _parse_workflow_board
from app.notifications.service import classify_ws_payload


def test_classify_board_updated() -> None:
    assert classify_ws_payload({"type": "board_updated"}) == "board"
    assert classify_ws_payload({"type": "tool_request"}) == "tool"
    assert classify_ws_payload({"type": "run_agent"}) == "command"
    assert classify_ws_payload({"type": "session_replaced"}) == "kick"
    assert classify_ws_payload({"type": "notification"}) == "notification"
    assert classify_ws_payload({"title": "Ping"}) == "notification"
    assert classify_ws_payload({"type": "pong"}) == "ignore"


def test_parse_live_board_payload() -> None:
    board = _parse_workflow_board(
        {
            "type": "board_updated",
            "stats": {"active_agents": 1, "runs_today": 7, "errors_today": 3, "next_run_at": "2026-08-21T08:00:00+00:00"},
            "agents": [{"id": "wf-1", "title": "Контроль", "status": "active", "last_run_at": "2026-08-21T07:15:00+00:00"}],
            "events": [{"id": "slot:1", "workflow_id": "wf-1", "status": "running", "start_at": "2026-08-21T07:15:00+00:00"}],
        }
    )
    assert board.stats.active_agents == 1
    assert board.stats.runs_today == 7
    assert board.agents[0].status == "active"
    assert board.events[0].status == "running"
