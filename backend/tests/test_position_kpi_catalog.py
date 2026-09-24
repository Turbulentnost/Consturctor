from __future__ import annotations

from kpi.kinds import FORMULA_KINDS, SOURCE_KINDS, SOURCE_ROLES
from kpi.seed_pl_npo_010 import CATALOG


def test_catalog_has_four_positions_and_weights_sum_100():
    assert len(CATALOG) == 4
    names = [item["position_name"] for item in CATALOG]
    assert "Помощник руководителя" in names
    assert "Помощник Председателя совета директоров" in names
    for item in CATALOG:
        assert sum(int(metric["weight"]) for metric in item["metrics"]) == 100
        for metric in item["metrics"]:
            assert metric["formula_kind"] in FORMULA_KINDS
            for source in metric["sources"]:
                assert source["role"] in SOURCE_ROLES
                assert source["kind"] in SOURCE_KINDS


def test_psd_uses_regulation_deadlines():
    psd = next(item for item in CATALOG if item["id"] == "plnpo010-psd")
    protocol = next(metric for metric in psd["metrics"] if metric["code"] == "protocol_on_time")
    assert protocol["plan_value"] == 95
    assert "T+2" in protocol["formula_human"]
    assert any(
        source.get("extra_json", {}).get("module") == "kpi.sources.sd_rk_protocols"
        for source in protocol["sources"]
    )
    package = next(metric for metric in psd["metrics"] if metric["code"] == "package_on_time")
    assert any(source.get("extra_json", {}).get("deadline") == "T-2d" for source in package["sources"])
    assert any(
        source.get("extra_json", {}).get("module") == "kpi.sources.sd_rk_packages"
        for source in package["sources"]
    )
    instructions = next(metric for metric in psd["metrics"] if metric["code"] == "instructions")
    assert instructions["formula_kind"] == "min_of"
    assert any(
        source.get("extra_json", {}).get("module") == "kpi.sources.sd_rk_instructions"
        for source in instructions["sources"]
    )
    quality = next(metric for metric in psd["metrics"] if metric["code"] == "quality")
    assert quality["formula_kind"] == "complement_ratio"
    assert any(
        source.get("extra_json", {}).get("module") == "kpi.sources.sd_rk_quality"
        and source.get("extra_json", {}).get("returns_assumed_zero") is True
        for source in quality["sources"]
    )
