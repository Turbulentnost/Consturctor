from datetime import datetime, timedelta, timezone

from app.ui.pages.my_agents_page import _TEMP, _active_word, _agents_word, _next_run_tile
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
