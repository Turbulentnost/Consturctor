from __future__ import annotations

from kpi.sources.sd_rk_quality import score_quality_kpi


def test_ilchenko_protocols_are_100_without_returns():
    report = score_quality_kpi(
        [
            {
                "number": "ПСД_001_О_225",
                "date": "2026-09-11",
                "status": "Подготовлен",
                "meeting_topic": "Совет директоров по ГК",
            },
            {
                "number": "РК__001_О_037",
                "date": "2026-09-08",
                "status": "НаИсполнении",
                "meeting_topic": "Еженедельное совещание с ревизионной комиссией",
            },
            {
                "number": "ПСД_001_О_231",
                "date": "2026-09-10",
                "status": "Закрыт",
                "meeting_topic": "Совещание по поручению АСТ00-00057",
            },
        ]
    )
    assert report["v_total"] == 2
    assert report["v_errors"] == 0
    assert report["fact_pct"] == 100
    assert report["score_pct"] == 100
    assert report["contrib_pct"] == 25
    assert all(row["returned"] is False for row in report["rows"])


def test_empty_protocols_have_no_fact():
    report = score_quality_kpi([])
    assert report["v_total"] == 0
    assert report["fact_pct"] is None
    assert report["score_pct"] is None
