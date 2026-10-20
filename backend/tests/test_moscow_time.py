from datetime import datetime, timezone

from app.services.moscow_time import moscow_day, odata_moscow


def test_odata_stamp_is_moscow_wall_clock_without_offset() -> None:
    stamp = odata_moscow(datetime(2026, 10, 15, 13, 10, tzinfo=timezone.utc))
    assert stamp == "2026-10-15T16:10:00"
    assert "Z" not in stamp and "+" not in stamp


def test_naive_clock_is_not_shifted() -> None:
    assert odata_moscow(datetime(2026, 10, 15, 16, 10, 5)) == "2026-10-15T16:10:05"


def test_moscow_day_follows_moscow_not_utc() -> None:
    assert moscow_day(datetime(2026, 10, 15, 22, 30, tzinfo=timezone.utc)) == "2026-10-16"
