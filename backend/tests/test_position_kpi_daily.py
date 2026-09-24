from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.jwt import AuthContext
from app.db.base import Base
from app.models.position_kpi import PositionKpiDailyFact
from app.services.position_kpi import daily as daily_mod
from app.services.position_kpi.daily import (
    PositionKpiNotFound,
    get_or_compute_position_kpi,
    refresh_all_profiles,
    resolve_profile,
)
from app.services.position_kpi.registry import SCORERS
from kpi.seed_pl_npo_010 import upsert_catalog

AS_OF = date(2026, 9, 22)
PERIOD_FROM = date(2026, 9, 1)
PERIOD_TO = date(2026, 9, 30)
PSD = "Помощник Председателя совета директоров"
OFFICE = "Офис-менеджер"


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    upsert_catalog(db)
    db.commit()
    return db


def _report(fact: float = 100.0) -> dict:
    return {
        "fact_pct": fact,
        "score_pct": fact,
        "contrib_pct": 25.0,
        "rows": [],
    }


def _scorer(label: str, counter: dict[str, int] | None = None, *, fail: bool = False):
    def _inner(metric, ctx):
        if counter is not None:
            counter[label] = counter.get(label, 0) + 1
        if fail:
            raise RuntimeError(f"{label} failed")
        return _report(), f"{label} ok"

    return _inner


def test_resolve_profile_exact_and_normalized() -> None:
    db = _session()
    exact = resolve_profile(db, PSD)
    assert exact is not None
    assert exact.id == "plnpo010-psd"
    folded = resolve_profile(db, "  помощник  председателя совета директоров  ")
    assert folded is not None
    assert folded.id == exact.id
    assert resolve_profile(db, "Неизвестная должность") is None
    assert resolve_profile(db, "") is None


def test_office_manager_returns_empty_tiles_and_does_not_load_sources(monkeypatch) -> None:
    db = _session()

    def boom(*_args, **_kwargs):
        raise AssertionError("source loader must not run without a scorer")

    monkeypatch.setattr(daily_mod, "load_outlook_events", boom)
    monkeypatch.setattr(daily_mod, "load_protocols", boom)
    monkeypatch.setattr(daily_mod, "load_cards", boom)

    first = get_or_compute_position_kpi(
        db,
        OFFICE,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
    )
    assert first["cached"] is False
    assert first["tiles"] == []
    assert first["profile_id"] == "plnpo010-office"
    assert first["position"] == OFFICE

    second = get_or_compute_position_kpi(
        db,
        OFFICE,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
    )
    assert second["cached"] is True
    assert second["tiles"] == []
    assert db.query(PositionKpiDailyFact).count() == 1


def test_assistant_scores_meetings_schedule_only(monkeypatch) -> None:
    db = _session()
    monkeypatch.setattr(
        daily_mod,
        "load_outlook_events",
        lambda *_a, **_k: [{"subject": "Планёрка директора", "start": "2026-09-10T10:00:00"}],
    )
    monkeypatch.setattr(daily_mod, "load_protocols", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError()))
    monkeypatch.setattr(daily_mod, "load_cards", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError()))

    def load_odata(self, extra):
        entity = extra.get("entity")
        if entity == "Catalog_Пользователи":
            return [{"Ref_Key": "leader", "Description": "Донцова Анна Егоровна"}]
        if entity == "Catalog_ТД_ТемыСовещаний":
            return [
                {
                    "Ref_Key": "t1",
                    "Description": "Планёрка директора",
                    "DeletionMark": False,
                    "ДатаЗакрытияТемы": "2026-12-31T00:00:00",
                    "ДеньВМесяце": 10,
                    "ПовторениеПоМесяцам": [{"Месяц": 9}],
                }
            ]
        if entity == "Document_ТД_Протокол":
            return [
                {
                    "DeletionMark": False,
                    "ВидСовещания": "Отчетное",
                    "ТемаСовещания_Key": "t1",
                    "Date": "2026-09-10T12:00:00",
                }
            ]
        raise AssertionError(entity)

    monkeypatch.setattr(daily_mod.SourceBundle, "load_odata", load_odata)

    def _skip_dpi(*_args, **_kwargs):
        raise RuntimeError("dpi is a separate test")

    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_dpi", _skip_dpi)
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_orders", _skip_dpi)
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_unplanned", _skip_dpi)
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_tasks", _skip_dpi)

    result = get_or_compute_position_kpi(
        db,
        "Помощник руководителя",
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
    )
    assert [tile["code"] for tile in result["tiles"]] == ["meetings_schedule"]
    assert result["tiles"][0]["score"] == 100
    assert result["tiles"][0]["fact"] == 100


def test_unknown_position_raises() -> None:
    db = _session()
    with pytest.raises(PositionKpiNotFound):
        get_or_compute_position_kpi(db, "Главный конструктор", as_of=AS_OF)


def test_psd_tiles_from_registry_and_cache_skips_recompute(monkeypatch) -> None:
    db = _session()
    calls: dict[str, int] = {}
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_packages", _scorer("package", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_protocols", _scorer("protocol", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_instructions", _scorer("instructions", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_quality", _scorer("quality", calls))

    first = get_or_compute_position_kpi(
        db,
        PSD,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
    )
    assert first["cached"] is False
    codes = [tile["code"] for tile in first["tiles"]]
    assert codes == ["package_on_time", "protocol_on_time", "instructions", "quality"]
    assert all(tile["fact"] == 100 for tile in first["tiles"])
    assert all(tile["score"] == 100 for tile in first["tiles"])
    assert calls == {"package": 1, "protocol": 1, "instructions": 1, "quality": 1}

    second = get_or_compute_position_kpi(
        db,
        PSD,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
    )
    assert second["cached"] is True
    assert [tile["code"] for tile in second["tiles"]] == codes
    assert calls == {"package": 1, "protocol": 1, "instructions": 1, "quality": 1}


def test_failed_scorer_skips_tile_not_response(monkeypatch) -> None:
    db = _session()
    calls: dict[str, int] = {}
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_packages", _scorer("package", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_protocols", _scorer("protocol", calls, fail=True))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_instructions", _scorer("instructions", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_quality", _scorer("quality", calls))

    result = get_or_compute_position_kpi(
        db,
        PSD,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
    )
    assert [tile["code"] for tile in result["tiles"]] == [
        "package_on_time",
        "instructions",
        "quality",
    ]
    assert calls["protocol"] == 1


def test_refresh_recomputes(monkeypatch) -> None:
    db = _session()
    calls: dict[str, int] = {}
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_packages", _scorer("package", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_protocols", _scorer("protocol", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_instructions", _scorer("instructions", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_quality", _scorer("quality", calls))

    get_or_compute_position_kpi(db, PSD, as_of=AS_OF, date_from=PERIOD_FROM, date_to=PERIOD_TO)
    refreshed = get_or_compute_position_kpi(
        db,
        PSD,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
        refresh=True,
    )
    assert refreshed["cached"] is False
    assert calls["package"] == 2


def test_allow_stale_returns_yesterday_without_recompute(monkeypatch) -> None:
    db = _session()
    calls: dict[str, int] = {}
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_packages", _scorer("package", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_protocols", _scorer("protocol", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_instructions", _scorer("instructions", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_quality", _scorer("quality", calls))

    yesterday = date(2026, 9, 21)
    get_or_compute_position_kpi(
        db,
        PSD,
        as_of=yesterday,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
    )
    assert calls["package"] == 1

    stale = get_or_compute_position_kpi(
        db,
        PSD,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
        allow_stale=True,
    )
    assert stale["cached"] is True
    assert stale["stale"] is True
    assert stale["as_of"] == yesterday.isoformat()
    assert calls["package"] == 1


def test_daily_cache_skips_profiles_already_computed_today(monkeypatch) -> None:
    db = _session()
    calls: dict[str, int] = {}
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_packages", _scorer("package", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_protocols", _scorer("protocol", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_instructions", _scorer("instructions", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_quality", _scorer("quality", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_meetings", _scorer("meetings", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_dpi", _scorer("dpi", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_orders", _scorer("orders", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_unplanned", _scorer("unplanned", calls))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_tasks", _scorer("tasks", calls))

    first = refresh_all_profiles(
        db,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
        force=False,
    )
    assert first["ok"] is True
    assert first["skipped"] == []
    assert set(first["computed"]) == {
        "plnpo010-psd",
        "plnpo010-assistant",
        "plnpo010-office",
        "plnpo010-archive",
    }
    assert calls["package"] == 1

    second = refresh_all_profiles(
        db,
        as_of=AS_OF,
        date_from=PERIOD_FROM,
        date_to=PERIOD_TO,
        force=False,
    )
    assert second["computed"] == []
    assert set(second["skipped"]) == set(first["computed"])
    assert calls["package"] == 1


def test_refresh_all_profiles_warms_catalog(monkeypatch) -> None:
    db = _session()
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_packages", _scorer("package"))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_protocols", _scorer("protocol"))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_instructions", _scorer("instructions"))
    monkeypatch.setitem(SCORERS, "kpi.sources.sd_rk_quality", _scorer("quality"))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_meetings", _scorer("meetings"))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_dpi", _scorer("dpi"))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_orders", _scorer("orders"))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_unplanned", _scorer("unplanned"))
    monkeypatch.setitem(SCORERS, "kpi.sources.assistant_tasks", _scorer("tasks"))

    result = refresh_all_profiles(db, as_of=AS_OF, date_from=PERIOD_FROM, date_to=PERIOD_TO)
    assert result["ok"] is True
    assert set(result["computed"]) == {
        "plnpo010-psd",
        "plnpo010-assistant",
        "plnpo010-office",
        "plnpo010-archive",
    }
    assert result["failed"] == []
    assert db.query(PositionKpiDailyFact).count() == 4


def test_api_uses_jwt_position_and_maps_errors(monkeypatch) -> None:
    from app.api.v1 import position_kpi as api

    captured: dict[str, str] = {}

    def fake_compute(_db, position, **_kwargs):
        captured["position"] = position
        return {
            "position": position,
            "profile_id": "plnpo010-office",
            "period_from": PERIOD_FROM.isoformat(),
            "period_to": PERIOD_TO.isoformat(),
            "as_of": AS_OF.isoformat(),
            "computed_at": "2026-09-22T08:00:00+00:00",
            "cached": True,
            "stale": False,
            "tiles": [],
        }

    monkeypatch.setattr(api, "get_or_compute_position_kpi", fake_compute)
    auth = AuthContext(user_id="u1", position=OFFICE)
    out = api.read_position_kpi(
        position="",
        period_from=None,
        period_to=None,
        refresh=False,
        auth=auth,
        db=None,
    )
    assert out.position == OFFICE
    assert captured["position"] == OFFICE

    with pytest.raises(HTTPException) as empty:
        api.read_position_kpi(
            position="",
            period_from=None,
            period_to=None,
            refresh=False,
            auth=AuthContext(user_id="u1"),
            db=None,
        )
    assert empty.value.status_code == 400

    monkeypatch.setattr(
        api,
        "get_or_compute_position_kpi",
        lambda *_a, **_k: (_ for _ in ()).throw(PositionKpiNotFound("x")),
    )
    with pytest.raises(HTTPException) as missing:
        api.read_position_kpi(
            position="нет такой",
            period_from=None,
            period_to=None,
            refresh=False,
            auth=auth,
            db=None,
        )
    assert missing.value.status_code == 404


def test_api_schedules_today_fill_when_stale(monkeypatch) -> None:
    from app.api.v1 import position_kpi as api

    scheduled: dict[str, object] = {}

    def fake_compute(_db, position, **_kwargs):
        return {
            "position": position,
            "profile_id": "plnpo010-office",
            "period_from": PERIOD_FROM.isoformat(),
            "period_to": PERIOD_TO.isoformat(),
            "as_of": "2026-09-21",
            "computed_at": "2026-09-21T08:00:00+00:00",
            "cached": True,
            "stale": True,
            "tiles": [],
        }

    monkeypatch.setattr(api, "get_or_compute_position_kpi", fake_compute)
    monkeypatch.setattr(
        api,
        "schedule_today_fill",
        lambda name, **kwargs: scheduled.update({"position": name, **kwargs}),
    )
    out = api.read_position_kpi(
        position=OFFICE,
        period_from=None,
        period_to=None,
        refresh=False,
        auth=AuthContext(user_id="u1"),
        db=None,
    )
    assert out.stale is True
    assert scheduled["position"] == OFFICE


def test_load_for_accepts_rows_and_skips_unknown() -> None:
    ctx = daily_mod.SourceBundle(as_of=AS_OF, date_from=PERIOD_FROM, date_to=PERIOD_TO)
    rows = ctx.load_for({"rows": [{"ok": True}, "skip", {"ok": False}]})
    assert rows == [{"ok": True}, {"ok": False}]
    assert ctx.load_for({"kind": "unknown", "note": "Турбопроект"}) == []
    assert ctx.load_for({"kind": "manual"}) == []
    assert ctx.load_for({"kind": "regulation"}) == []


def test_celery_beat_includes_position_kpi_daily() -> None:
    from app.celery_app import celery_app

    item = celery_app.conf.beat_schedule["refresh-position-kpi-daily"]
    assert item["task"] == "app.tasks.scheduled.refresh_position_kpi_daily"
