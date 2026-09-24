from __future__ import annotations

from app.services.position_kpi.extract import extract_position_kpis

SAMPLE = """
Положение о материальном стимулировании

Должность: Ведущий специалист отдела кадров

1. Своевременность кадровых приказов — вес 50%. Факт = доля приказов, изданных не позднее плановой даты. Цель ≥ 95%. Источник: 1С Document_ТД_Приказ.
2. Полнота личного дела — вес 40%. Менее 5 нарушений → 100%, от 5 до 8 → 50%, более 8 → 0%.
3. Индивидуальные задачи — вес 10%. Оценка по форме 02-58.

Должность: Архивариус

1. Приём документов в архив — вес 30%.
"""


def test_extracts_metrics_for_named_position() -> None:
    result = extract_position_kpis(SAMPLE, "Ведущий специалист отдела кадров")
    assert result["needs_position_choice"] is False
    assert result["position"] == "Ведущий специалист отдела кадров"
    codes = [item["code"] for item in result["metrics"]]
    assert len(result["metrics"]) == 3
    assert any("prikaz" in code or "kadrov" in code or "svoevremennost" in code for code in codes)
    first = result["metrics"][0]
    assert first["weight"] == 50
    assert first["plan_value"] == 95
    assert first["formula_kind"] == "gate_then_ratio"
    assert any(
        source.get("extra_json", {}).get("entity") == "Document_ТД_Приказ"
        for source in first["sources"]
    )


def test_asks_which_position_when_several_and_no_match() -> None:
    result = extract_position_kpis(SAMPLE, "Секретарь")
    assert result["needs_position_choice"] is True
    assert "Архивариус" in result["positions"]
    assert result["metrics"] == []


def test_empty_text_returns_no_metrics() -> None:
    result = extract_position_kpis("", "Секретарь")
    assert result["metrics"] == []
    assert result["needs_position_choice"] is False
