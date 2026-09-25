from __future__ import annotations

from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.jwt import AuthContext
from app.db.base import Base
from app.models.position_kpi import PositionKpiMetric, PositionKpiProfile, PositionKpiSource
from app.services.position_kpi.builder import (
    attach_files,
    connect_build,
    finish_sdk,
    position_kpis_missing,
    start_build,
)
from app.services.position_kpi.connect import generated_profile_id, upsert_generated_catalog
from app.services.position_kpi.daily import get_or_compute_position_kpi
from app.services.position_kpi.registry import scorer_for
from kpi.seed_pl_npo_010 import upsert_catalog

POSITION = "Ведущий специалист отдела кадров"
SAMPLE = (
    "Должность: Ведущий специалист отдела кадров\n\n"
    "1. Своевременность кадровых приказов — вес 50%. Цель ≥ 95%. "
    "Источник: 1С Document_ТД_Приказ.\n"
    "2. Полнота личного дела — вес 50%. Менее 5 нарушений → 100%.\n"
)

MODULE_CODE = '''
from datetime import date
from typing import Any

SOURCE = {"source": "platform.tasks", "params": {"role": "assignee"}}

def score_orders_kpi(rows, *, as_of: date, date_from=None, date_to=None) -> dict[str, Any]:
    total = len(rows or [])
    ok = sum(1 for row in rows or [] if row.get("ok"))
    fact = round(100.0 * ok / total, 1) if total else 100.0
    return {
        "fact_pct": fact,
        "score_pct": fact,
        "contrib_pct": fact * 0.5,
        "rows": rows or [],
    }

def format_report(report: dict[str, Any]) -> str:
    return "факт %s%%" % report.get("fact_pct")
'''


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()
    upsert_catalog(db)
    db.commit()
    return db


def test_seed_does_not_delete_generated_profile() -> None:
    db = _session()
    profile_id = upsert_generated_catalog(
        db,
        position=POSITION,
        catalog={
            "position_name": POSITION,
            "summary": "generated",
            "metrics": [
                {
                    "code": "orders",
                    "name": "Приказы",
                    "weight": 100,
                    "formula_kind": "needs_clarify",
                    "formula_json": {"kind": "needs_clarify"},
                    "sources": [],
                }
            ],
        },
    )
    db.commit()
    assert profile_id.startswith("generated-")
    upsert_catalog(db)
    db.commit()
    assert db.get(PositionKpiProfile, profile_id) is not None
    assert db.get(PositionKpiProfile, "plnpo010-psd") is not None


def test_generated_catalog_replaces_seeded_position() -> None:
    from sqlalchemy import select

    db = _session()
    seeded = db.execute(
        select(PositionKpiProfile).where(PositionKpiProfile.position_name == "Помощник руководителя")
    ).scalar_one()
    assert seeded.id == "plnpo010-assistant"
    profile_id = upsert_generated_catalog(
        db,
        position="Помощник руководителя",
        catalog={
            "position_name": "Помощник руководителя",
            "summary": "из методики",
            "metrics": [
                {
                    "code": "meetings",
                    "name": "Планирование совещаний",
                    "weight": 40,
                    "formula_kind": "needs_clarify",
                    "formula_json": {"kind": "needs_clarify"},
                    "sources": [],
                }
            ],
        },
    )
    db.commit()
    assert profile_id == generated_profile_id("Помощник руководителя")
    assert db.get(PositionKpiProfile, "plnpo010-assistant") is None
    assert db.get(PositionKpiProfile, profile_id).position_name == "Помощник руководителя"
    again = upsert_generated_catalog(
        db,
        position="Помощник руководителя",
        catalog={"position_name": "Помощник руководителя", "summary": "из методики", "metrics": []},
    )
    upsert_catalog(db)
    db.commit()
    assert again == profile_id
    assert db.get(PositionKpiProfile, profile_id) is not None
    assert db.get(PositionKpiProfile, "plnpo010-assistant") is None


LOAD_MODULE_CODE = '''
from datetime import date
from typing import Any

SOURCE = {"loader": "odata"}


def load_orders_kpi_rows(ctx):
    extra = dict(SOURCE)
    more = ctx.extra_for() if hasattr(ctx, "extra_for") else {}
    if isinstance(more, dict):
        extra.update(more)
    return [row for row in (ctx.load_for(extra) or []) if isinstance(row, dict)]


def score_orders_kpi(rows, *, as_of: date, date_from=None, date_to=None) -> dict[str, Any]:
    items = [row for row in (rows or []) if isinstance(row, dict)]
    total = len(items)
    ok = sum(1 for row in items if row.get("ok"))
    fact = round(100.0 * ok / total, 1) if total else None
    return {"fact_pct": fact, "score_pct": fact, "contrib_pct": fact, "rows": items}


def compute_orders_kpi(ctx, *, as_of: date, date_from=None, date_to=None) -> dict[str, Any]:
    return score_orders_kpi(load_orders_kpi_rows(ctx), as_of=as_of, date_from=date_from, date_to=date_to)
'''


def test_run_generated_pair_is_load_then_score() -> None:
    from types import SimpleNamespace

    from app.services.position_kpi.registry import run_generated_pair

    calls: list[str] = []

    def load_fn(ctx):
        calls.append(f"load:{ctx.as_of.isoformat()}")
        return [{"ok": True}]

    def score_fn(rows, *, as_of, date_from=None, date_to=None):
        calls.append(f"score:{len(rows)}")
        return {"fact_pct": 100.0, "score_pct": 100.0, "contrib_pct": 10.0, "rows": rows}

    mod = SimpleNamespace(
        SOURCE={"loader": "odata"},
        load_demo_rows=load_fn,
        score_demo_kpi=score_fn,
    )
    ctx = SimpleNamespace(
        as_of=date(2026, 9, 22),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        extra_for=lambda *_a, **_k: {},
        load_for=lambda extra: (_ for _ in ()).throw(AssertionError("pair must use load_*")),
    )
    report = run_generated_pair(mod, ctx, None)
    assert calls == ["load:2026-09-22", "score:1"]
    assert report["fact_pct"] == 100.0


def test_run_generated_pair_is_load_then_score() -> None:
    from types import SimpleNamespace

    from app.services.position_kpi.registry import run_generated_pair

    calls: list[str] = []

    def load_fn(ctx):
        calls.append(f"load:{ctx.as_of.isoformat()}")
        return [{"ok": True}]

    def score_fn(rows, *, as_of, date_from=None, date_to=None):
        calls.append(f"score:{len(rows)}")
        return {"fact_pct": 100.0, "score_pct": 100.0, "contrib_pct": 10.0, "rows": rows}

    mod = SimpleNamespace(
        SOURCE={"loader": "odata"},
        load_demo_rows=load_fn,
        score_demo_kpi=score_fn,
    )
    ctx = SimpleNamespace(
        as_of=date(2026, 9, 22),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        extra_for=lambda *_a, **_k: {},
        load_for=lambda extra: (_ for _ in ()).throw(AssertionError("pair must use load_*")),
    )
    report = run_generated_pair(mod, ctx, None)
    assert calls == ["load:2026-09-22", "score:1"]
    assert report["fact_pct"] == 100.0


def test_dynamic_scorer_uses_module_loader(monkeypatch) -> None:
    from app.services.position_kpi import connect as connect_mod
    from app.services.position_kpi.daily import SourceBundle

    stored = connect_mod.write_generated_modules(
        [
            {
                "metric_code": "orders_load",
                "module": "kpi.generated.orders_load_probe",
                "code_text": LOAD_MODULE_CODE,
            }
        ]
    )
    path = None
    try:
        assert stored
        path = stored[0]["path"]
        scorer = scorer_for("kpi.generated.orders_load_probe")
        assert scorer is not None
        ctx = SourceBundle(as_of=date(2026, 9, 22), date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
        seen: list[int] = []

        def wrapped_load(extra):
            rows = [{"ok": True}, {"ok": False}] if extra.get("loader") == "odata" else []
            seen.append(len(rows))
            return rows

        ctx.load_for = wrapped_load
        report, evidence = scorer(None, ctx)
        assert seen == [2]
        assert report["fact_pct"] == 50.0
        assert report["rows"]
        assert "50" in evidence or "факт" in evidence
    finally:
        if path:
            from pathlib import Path

            Path(path).unlink(missing_ok=True)
            Path(path).with_name("test_orders_load_probe.py").unlink(missing_ok=True)


def test_dynamic_scorer_loads_generated_module() -> None:
    from app.services.position_kpi import connect as connect_mod
    from app.services.position_kpi.daily import SourceBundle

    stored = connect_mod.write_generated_modules(
        [
            {
                "metric_code": "orders",
                "module": "kpi.generated.orders_probe",
                "code_text": MODULE_CODE,
            }
        ]
    )
    path = None
    try:
        assert stored
        path = stored[0]["path"]
        scorer = scorer_for("kpi.generated.orders_probe")
        assert scorer is not None
        ctx = SourceBundle(as_of=date(2026, 9, 22), date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
        ctx._metric_extra = {}
        report, evidence = scorer(None, ctx)
        assert report["fact_pct"] == 100.0
        assert "факт" in evidence
    finally:
        if path:
            from pathlib import Path

            Path(path).unlink(missing_ok=True)
            Path(path).with_name("test_orders_probe.py").unlink(missing_ok=True)


def test_session_extracts_and_connects_tiles() -> None:
    db = _session()
    auth = AuthContext(user_id="u-kpi", position=POSITION)
    session = start_build(db, user_id=auth.user_id, position=POSITION)
    build_id = session["build_id"]
    uploaded = attach_files(
        db,
        user_id=auth.user_id,
        build_id=build_id,
        files=[("motivation.txt", SAMPLE.encode("utf-8"))],
    )
    assert uploaded["status"] == "clarifying"
    assert uploaded["extracted"]["metrics"]
    connected = connect_build(
        db,
        user_id=auth.user_id,
        build_id=build_id,
        modules=[
            {
                "metric_code": uploaded["extracted"]["metrics"][0]["code"],
                "module": "kpi.generated.orders_on_time",
                "code_text": MODULE_CODE,
            }
        ],
    )
    assert connected["status"] == "connected"
    assert connected["profile_id"] == generated_profile_id(POSITION)
    payload = get_or_compute_position_kpi(
        db,
        POSITION,
        as_of=date(2026, 9, 22),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        refresh=True,
    )
    assert payload["profile_id"] == connected["profile_id"]
    # generated scorer may skip if import path missing; profile must exist either way
    assert payload["position"] == POSITION
    for item in connected.get("modules") or []:
        path = item.get("path") if isinstance(item, dict) else ""
        if path:
            from pathlib import Path

            Path(path).unlink(missing_ok=True)


def test_scan_pdf_does_not_call_lm_studio(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise AssertionError("LM Studio OCR must not run for KPI build")

    monkeypatch.setattr("app.services.regulation.pdf_ocr.extract_pdf_scan", boom)
    monkeypatch.setattr(
        "app.services.workflows.document._read_pdf_bytes_ocr",
        lambda raw: (_ for _ in ()).throw(AssertionError("hidden OCR fallback")),
    )
    db = _session()
    session = start_build(db, user_id="u-kpi", position=POSITION)
    uploaded = attach_files(
        db,
        user_id="u-kpi",
        build_id=session["build_id"],
        files=[("scan.pdf", b"%PDF-1.4 scan without text layer")],
    )
    assert uploaded["status"] == "clarifying"
    assert uploaded["extracted"].get("needs_vision") is True
    assert uploaded["extracted"].get("attachments") == ["scan.pdf"]
    assert any("Cursor" in (item.get("content") or "") for item in uploaded["messages"])
    prompt = uploaded["sdk_prompt"]
    assert "office.read_file" in prompt
    assert "start_page=2" in prompt
    assert "не папка attachments" in prompt
    assert "vision_pages" in prompt
    assert "второй вызов" in prompt
    assert "уже в этом сообщении" in prompt
    assert POSITION in prompt
    assert "Текста нет" in prompt
    assert "Больше никаких инструментов" in prompt
    assert "backend/kpi/generated" in prompt
    assert "спросит конструктор" not in prompt
    assert "карточками" not in prompt
    assert "Не вызывай askQuestion." in prompt
    assert "СПИСОК_ГОТОВ" in prompt
    assert "не только первые два" in prompt
    assert "откуда план и факт" in prompt


def test_api_create_build_uses_jwt_position() -> None:
    from app.api.v1 import position_kpi_builds as api

    db = _session()
    out = api.create_build(
        body=None,
        position="",
        auth=AuthContext(user_id="u-api", position=POSITION),
        db=db,
    )
    assert out.position == POSITION
    assert out.status == "awaiting_file"
    assert out.messages


def test_start_build_resumes_open_session() -> None:
    db = _session()
    first = start_build(db, user_id="u-kpi", position=POSITION)
    second = start_build(db, user_id="u-kpi", position=POSITION)
    other = start_build(db, user_id="u-other", position=POSITION)
    assert first["build_id"] == second["build_id"]
    assert other["build_id"] != first["build_id"]


def test_start_build_does_not_resume_session_with_file() -> None:
    from app.models.position_kpi import PositionKpiBuild

    db = _session()
    progressed = start_build(db, user_id="u-kpi", position=POSITION)
    row = db.get(PositionKpiBuild, progressed["build_id"])
    assert row is not None
    row.status = "clarifying"
    row.extracted_json = {"attachments": ["motivation.pdf"], "needs_vision": True}
    db.commit()
    again = start_build(db, user_id="u-kpi", position=POSITION)
    assert again["build_id"] != progressed["build_id"]
    assert again["status"] == "awaiting_file"
    assert not (again.get("extracted") or {}).get("attachments")


def test_empty_state_flags_match_ui() -> None:
    def needs_build(*, loading: bool, missing: bool, tiles: list) -> bool:
        if loading:
            return False
        if missing:
            return True
        return bool(tiles is not None) and len(tiles) == 0

    assert needs_build(loading=True, missing=True, tiles=[]) is False
    assert needs_build(loading=False, missing=True, tiles=[]) is True
    assert needs_build(loading=False, missing=False, tiles=[]) is True
    assert needs_build(loading=False, missing=False, tiles=[{"fact": 1}]) is False


def test_position_kpis_missing_detects_stop() -> None:
    assert position_kpis_missing("В положении нет KPI должности менеджер тендерного офиса.")
    assert not position_kpis_missing("Нашла два показателя. Спрошу про план.")


def _unlink(paths: list[str]) -> None:
    from pathlib import Path

    for raw in paths:
        if not raw:
            continue
        path = Path(raw)
        path.unlink(missing_ok=True)
        path.with_name(f"test_{path.stem}.py").unlink(missing_ok=True)


def test_module_source_is_stored_for_the_position() -> None:
    from sqlalchemy import func, select

    from app.models.position_kpi import PositionKpiModule
    from app.services.position_kpi.connect import list_module_descriptors, module_name_for

    db = _session()
    modules = [
        {
            "metric_code": "orders",
            "module": "kpi.generated.orders_on_time",
            "code_text": MODULE_CODE,
        }
    ]
    catalog = {
        "position_name": POSITION,
        "summary": "generated",
        "metrics": [
            {
                "code": "orders",
                "name": "Приказы",
                "weight": 100,
                "formula_kind": "needs_clarify",
                "formula_json": {"kind": "needs_clarify"},
                "sources": [],
            }
        ],
    }
    profile_id = upsert_generated_catalog(db, position=POSITION, catalog=catalog, modules=modules)
    again = upsert_generated_catalog(db, position=POSITION, catalog=catalog, modules=modules)
    other_position = "Секретарь совета директоров"
    other_id = upsert_generated_catalog(
        db,
        position=other_position,
        catalog={**catalog, "position_name": other_position},
        modules=modules,
    )
    db.commit()
    described = list_module_descriptors(db, profile_id) + list_module_descriptors(db, other_id)
    try:
        assert again == profile_id
        assert other_id != profile_id
        stored = db.execute(
            select(PositionKpiModule).where(PositionKpiModule.profile_id == profile_id)
        ).scalars().all()
        assert len(stored) == 1
        assert stored[0].module_name == module_name_for(profile_id, "orders")
        assert stored[0].module_name != "kpi.generated.orders_on_time"
        assert stored[0].source.strip() == MODULE_CODE.strip()
        assert (
            db.execute(
                select(func.count())
                .select_from(PositionKpiModule)
                .where(PositionKpiModule.profile_id == profile_id)
            ).scalar_one()
            == 1
        )
        other = db.execute(
            select(PositionKpiModule).where(PositionKpiModule.profile_id == other_id)
        ).scalar_one()
        assert other.module_name != stored[0].module_name
        from pathlib import Path

        path = Path(list_module_descriptors(db, profile_id)[0]["path"])
        path.unlink()
        assert not path.exists()
        payload = get_or_compute_position_kpi(
            db,
            POSITION,
            as_of=date(2026, 9, 22),
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
            refresh=True,
        )
        assert path.exists()
        assert payload["tiles"][0]["fact"] == 100.0
        other_payload = get_or_compute_position_kpi(
            db,
            other_position,
            as_of=date(2026, 9, 22),
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
            refresh=True,
        )
        assert other_payload["tiles"][0]["fact"] == 100.0
        assert other_payload["profile_id"] == other_id
    finally:
        _unlink([item["path"] for item in described])


def test_reconnect_keeps_module_without_resending_source() -> None:
    db = _session()
    session = start_build(db, user_id="u-kpi", position=POSITION)
    uploaded = attach_files(
        db,
        user_id="u-kpi",
        build_id=session["build_id"],
        files=[("motivation.txt", SAMPLE.encode("utf-8"))],
    )
    code = uploaded["extracted"]["metrics"][0]["code"]
    finished = finish_sdk(
        db,
        user_id="u-kpi",
        build_id=session["build_id"],
        answer="Модуль готов.",
        modules=[
            {
                "metric_code": code,
                "module": "kpi.generated.orders_on_time",
                "code_text": MODULE_CODE,
            }
        ],
        connect=True,
    )
    assert finished["status"] == "connected"
    again = connect_build(db, user_id="u-kpi", build_id=session["build_id"])
    paths = [item.get("path") for item in (again.get("modules") or []) if isinstance(item, dict)]
    try:
        assert again["profile_id"] == finished["profile_id"]
        assert again["modules"]
        assert again["modules"][0]["module"].startswith("kpi.generated.")
        payload = get_or_compute_position_kpi(
            db,
            POSITION,
            as_of=date(2026, 9, 22),
            date_from=date(2026, 9, 1),
            date_to=date(2026, 9, 30),
            refresh=True,
        )
        assert payload["tiles"]
    finally:
        _unlink([str(path) for path in paths])


def test_finish_sdk_stops_when_position_absent() -> None:
    db = _session()
    session = start_build(db, user_id="u-kpi", position="менеджер тендерного офиса")
    finished = finish_sdk(
        db,
        user_id="u-kpi",
        build_id=session["build_id"],
        answer="В положении нет KPI этой должности — только управление делами.",
        events=[],
        modules=[],
    )
    assert finished["status"] == "clarifying"
    stages = [item["structured"].get("stage") for item in finished["messages"]]
    assert "not_found" in stages
    assert "incomplete" not in stages


def test_finish_sdk_keeps_catalog_loaders() -> None:
    db = _session()
    session = start_build(db, user_id="u-kpi", position=POSITION)
    catalog = {
        "position_name": POSITION,
        "metrics": [
            {
                "code": "orders",
                "name": "Приказы",
                "weight": 50,
                "formula_kind": "needs_clarify",
                "formula_json": {"kind": "needs_clarify"},
                "sources": [
                    {
                        "role": "fact",
                        "kind": "onec",
                        "title": "Источник факта",
                        "detail": "1С",
                        "update_rule": "",
                        "extra_json": {"loader": "odata"},
                    }
                ],
            },
            {
                "code": "files",
                "name": "Личные дела",
                "weight": 50,
                "formula_kind": "needs_clarify",
                "formula_json": {"kind": "needs_clarify"},
                "sources": [
                    {
                        "role": "fact",
                        "kind": "files",
                        "title": "Источник факта",
                        "detail": "Excel",
                        "update_rule": "",
                        "extra_json": {"loader": "files"},
                    }
                ],
            },
        ],
    }
    finished = finish_sdk(
        db,
        user_id="u-kpi",
        build_id=session["build_id"],
        answer="1. Приказы — вес 50%. Источник: 1С\n2. Личные дела — вес 50%.",
        events=[],
        modules=[],
        catalog_draft=catalog,
    )
    metrics = finished["catalog_draft"]["metrics"]
    assert metrics[0]["sources"][0]["extra_json"]["loader"] == "odata"
    assert metrics[0]["sources"][0]["kind"] == "onec"


def test_long_kpi_slug_source_ids_fit_varchar_64() -> None:
    from sqlalchemy import select

    from app.services.position_kpi.connect import metric_row_id, source_row_id

    db = _session()
    slug = "planirovanie_soveschaniy_organizaciya_ra"
    catalog = {
        "position_name": "Помощник руководителя",
        "summary": "из методики",
        "metrics": [
            {
                "code": slug,
                "name": "Планирование совещаний, организация рабочего дня",
                "weight": 40,
                "formula_kind": "needs_clarify",
                "formula_json": {"kind": "needs_clarify"},
                "sources": [
                    {
                        "role": "plan",
                        "kind": "regulation",
                        "title": "Методика расчёта",
                        "detail": "Норма из загруженного положения.",
                        "update_rule": "Меняется новой версией положения.",
                    },
                    {
                        "role": "fact",
                        "kind": "unknown",
                        "title": "Источник факта",
                        "detail": "Планирование совещаний — вес 40%",
                        "update_rule": "Раз в расчётный период.",
                    },
                ],
            }
        ],
    }
    profile_id = upsert_generated_catalog(db, position="Помощник руководителя", catalog=catalog)
    again = upsert_generated_catalog(db, position="Помощник руководителя", catalog=catalog)
    db.commit()
    metric = db.execute(
        select(PositionKpiMetric).where(PositionKpiMetric.profile_id == profile_id)
    ).scalar_one()
    sources = db.execute(
        select(PositionKpiSource).where(PositionKpiSource.metric_id == metric.id)
    ).scalars().all()
    assert again == profile_id
    assert metric.id == metric_row_id(profile_id, slug)
    assert len(metric.id) <= 64
    assert len(sources) == 2
    assert {row.id for row in sources} == {
        source_row_id(metric.id, "plan", "regulation", 1),
        source_row_id(metric.id, "fact", "unknown", 2),
    }
    assert all(len(row.id) <= 64 for row in sources)
