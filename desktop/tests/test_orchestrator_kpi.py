from app.orchestrator.kpi import (
    format_percent,
    has_position_kpi,
    score_rows,
    seed_ilchenko_instances,
    weighted_score,
)


def test_ilchenko_seed_scores() -> None:
    rows = score_rows(seed_ilchenko_instances())
    assert [row.number for row in rows] == [1, 2, 3, 4]
    assert rows[0].fact == 100
    assert rows[3].fact is not None and rows[3].fact < 98
    assert weighted_score(rows) is not None
    assert format_percent(95) == "95%"


def test_position_kpi_matches_ilchenko() -> None:
    assert has_position_kpi("A2DCC949FEDEC70D40318ABA83C618F4")
    assert has_position_kpi(fio="Ильченко Екатерина Александровна")
    assert not has_position_kpi("other-user", "Другой Пользователь")
