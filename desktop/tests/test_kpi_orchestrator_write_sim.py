from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from app.sdk_agent.kpi_attach import (
    KPI_MODULE_SAMPLE,
    KPI_MODULE_SAMPLE_TEST,
    catalog_from_jobs,
    kpi_write_jobs,
    write_kpi_example_files,
)


POSITION = "Помощник руководителя"
NAME = "Планирование совещаний / организация работы"
WEIGHT = "40"
SOURCE = "план и факт из отчёта 1С"
SLUG = "planirovanie_soveschaniy_organizaciya_ra"


def _jobs() -> list[dict[str, str]]:
    return kpi_write_jobs(
        [{"name": NAME, "weight": WEIGHT, "source": SOURCE, "slug": SLUG}],
        position=POSITION,
    )


def _write_as_orchestrator_agent(workspace: Path, slug: str, weight: str) -> None:
    """То, что write-ход обязан положить по образцу examples/orders_on_time.py."""
    write_kpi_example_files(workspace / "examples")
    (workspace / "generated").mkdir(parents=True, exist_ok=True)
    (workspace / "tests").mkdir(parents=True, exist_ok=True)
    (workspace / "generated" / "__init__.py").write_text(
        '"""KPI modules for this build."""\n',
        encoding="utf-8",
    )
    module = (
        KPI_MODULE_SAMPLE.replace("orders_on_time", slug)
        .replace("fact * 50 / 100.0", f"fact * {weight} / 100.0")
        .replace('SOURCE = {"loader": "odata"}', 'SOURCE = {"kind": "onec", "loader": "odata"}')
    )
    test = (
        KPI_MODULE_SAMPLE_TEST.replace("orders_on_time", slug)
        .replace('assert extra.get("loader") == "odata"', 'assert extra.get("loader") == "odata"')
    )
    (workspace / "generated" / f"{slug}.py").write_text(module, encoding="utf-8")
    (workspace / "tests" / f"test_{slug}.py").write_text(test, encoding="utf-8")


def test_write_prompt_forbids_invented_entity_and_requires_tandem() -> None:
    job = _jobs()[0]
    prompt = job["prompt"]
    assert job["slug"] == SLUG
    assert "load_planirovanie_soveschaniy_organizaciya_ra_rows(ctx)" in prompt
    assert "compute_planirovanie_soveschaniy_organizaciya_ra_kpi(ctx" in prompt
    assert "Имена EntitySet не выдумывай" in prompt
    assert "onec.odata_catalog" in prompt
    assert "Не читай PDF" in prompt
    assert "Catalog_ТД_ТемыСовещаний" not in prompt
    catalog = catalog_from_jobs(_jobs(), position=POSITION)
    extra = catalog["metrics"][0]["sources"][1]["extra_json"]
    assert extra["loader"] == "odata"
    assert "entity" not in extra


def test_orchestrator_write_then_pytest_and_compute(tmp_path: Path) -> None:
    _write_as_orchestrator_agent(tmp_path, SLUG, WEIGHT)
    sidecar_mod = _load_orch_sidecar()
    ok, output = sidecar_mod._run_kpi_slug_tests(tmp_path, SLUG)
    assert ok, output

    import importlib
    import sys

    sys.path.insert(0, str(tmp_path))
    sys.modules.pop(f"generated.{SLUG}", None)
    sys.modules.pop("generated", None)
    mod = importlib.import_module(f"generated.{SLUG}")
    assert callable(mod.load_planirovanie_soveschaniy_organizaciya_ra_rows)
    assert callable(mod.score_planirovanie_soveschaniy_organizaciya_ra_kpi)
    assert callable(mod.compute_planirovanie_soveschaniy_organizaciya_ra_kpi)

    class _FakeCtx:
        def extra_for(self, *_a, **_k):
            return {}

        def load_for(self, extra):
            assert extra.get("loader") == "odata"
            assert extra.get("kind") == "onec"
            assert not extra.get("entity")
            return [{"on_time": True}, {"plan": "2026-09-10", "fact": "2026-09-11"}]

    report = mod.compute_planirovanie_soveschaniy_organizaciya_ra_kpi(
        _FakeCtx(),
        as_of=date(2026, 9, 22),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert report["fact_pct"] == 50.0
    assert report["contrib_pct"] == 20.0
    assert len(report["rows"]) == 2


def test_daily_pair_uses_compute_not_live_bypass(tmp_path: Path, monkeypatch) -> None:
    _write_as_orchestrator_agent(tmp_path, SLUG, WEIGHT)
    import importlib
    import sys

    sys.path.insert(0, str(tmp_path))
    sys.modules.pop(f"generated.{SLUG}", None)
    sys.modules.pop("generated", None)
    mod = importlib.import_module(f"generated.{SLUG}")

    backend = Path(__file__).resolve().parents[2] / "backend"
    if str(backend) not in sys.path:
        sys.path.append(str(backend))

    # desktop `app` is already imported; load registry by file to avoid clash
    import importlib.util

    registry_path = backend / "app" / "services" / "position_kpi" / "registry.py"
    spec = importlib.util.spec_from_file_location("kpi_registry_sim", registry_path)
    registry = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(registry)

    calls: list[str] = []

    def load_for(extra):
        calls.append(str(extra.get("loader")))
        return [{"on_time": True}, {"on_time": False}]

    ctx = SimpleNamespace(
        as_of=date(2026, 9, 22),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        extra_for=lambda *_a, **_k: {},
        load_for=load_for,
    )
    report = registry.run_generated_pair(mod, ctx, None)
    assert calls == ["odata"]
    assert report["fact_pct"] == 50.0
    assert report["contrib_pct"] == 20.0


def _load_orch_sidecar():
    import sys

    root = Path(__file__).resolve().parents[2]
    pybridge = str(root / "orchestrator" / "desktop-electron" / "pybridge")
    if pybridge not in sys.path:
        sys.path.insert(0, pybridge)
    import agent_sidecar as sidecar_mod

    return sidecar_mod
