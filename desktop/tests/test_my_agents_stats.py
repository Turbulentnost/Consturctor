from datetime import datetime, timedelta, timezone

from app.api_client import (
    AgentSuggestion,
    BoardAgent,
    BoardStats,
    CalendarEvent,
    WorkflowBoard,
    without_deleted_workflows,
)
from app.ui.pages.my_agents_page import (
    _TEMP,
    _active_word,
    _agents_word,
    _next_run_tile,
    _normalize_title,
    draft_or_agent_matches,
)
from app.ui.widgets.run_calendar import _runs_word


def test_stat_tile_icons_exist() -> None:
    for name in ("agents.png", "puls.png", "start.png", "time.png"):
        assert (_TEMP / name).is_file()


def test_stat_tile_wording() -> None:
    assert f"3 {_agents_word(3)}" == "3 агента"
    assert f"1 {_agents_word(1)}" == "1 агент"
    assert f"5 {_agents_word(5)}" == "5 агентов"
    assert f"2 {_active_word(2)}" == "2 активны"
    assert f"1 {_active_word(1)}" == "1 активен"
    assert f"1 {_runs_word(1)} сегодня" == "1 запуск сегодня"


def test_next_run_tile_today() -> None:
    stamp = datetime.now(timezone.utc).replace(hour=11, minute=0, second=0, microsecond=0)
    text = _next_run_tile(stamp.isoformat())
    assert text.startswith("Ближайший – ")
    assert _next_run_tile("") == "Ближайший – нет"
    later = datetime.now(timezone.utc) + timedelta(days=2)
    assert "," in _next_run_tile(later.isoformat())
    due = datetime.now(timezone.utc) - timedelta(minutes=2)
    assert _next_run_tile(due.isoformat()) == "Ближайший – сейчас"
    upcoming = datetime.now(timezone.utc) + timedelta(hours=3)
    assert "сейчас" not in _next_run_tile(upcoming.isoformat())


def test_without_deleted_workflows_hides_agent_and_future_slots() -> None:
    board = WorkflowBoard(
        stats=BoardStats(active_agents=1, next_run_at="2026-08-24T09:00:00+00:00"),
        agents=[
            BoardAgent(id="wf-1", kind="workflow", title="Контроль", status="active", next_run_at="2026-08-24T09:00:00+00:00"),
            BoardAgent(id="draft-1", kind="draft", title="Черновик", status="draft"),
        ],
        events=[
            CalendarEvent(id="past", workflow_id="wf-1", start_at="2026-08-24T07:00:00+00:00", status="error", is_future=False),
            CalendarEvent(id="future", workflow_id="wf-1", start_at="2026-08-24T09:00:00+00:00", status="scheduled", is_future=True),
        ],
    )
    cleaned = without_deleted_workflows(board, {"wf-1"})
    assert [item.id for item in cleaned.agents] == ["draft-1"]
    assert [item.id for item in cleaned.events] == ["past"]
    assert cleaned.stats.active_agents == 0
    assert cleaned.stats.next_run_at == ""


def test_normalize_title_for_formed_agents() -> None:
    assert _normalize_title("  Контроль сроков  ") == "контроль сроков"


def test_draft_search_matches_embedded_agents() -> None:
    agent = BoardAgent(id="d1", kind="draft", title="Регламент внедрения", draft_id="d1")
    suggestions = [
        AgentSuggestion(
            agent_id="a1",
            title="Kontrol srokov",
            description="Sledit za deglajnami",
            regulation_id="r1",
            role_match_run_id="",
            function_id="",
            source_block_id="",
        )
    ]
    assert draft_or_agent_matches(agent, "srokov", suggestions) is True
    assert draft_or_agent_matches(agent, "otpusk", suggestions) is False
