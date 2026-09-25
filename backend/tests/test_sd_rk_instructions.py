from __future__ import annotations

from datetime import date

from kpi.instruction_tracker import compute_tile_update, load_tracker
from kpi.sources.sd_rk_instructions import (
    classify_instruction,
    is_protocol_dump,
    score_instruction_kpi,
    within_24h,
)
from kpi.sources.sd_rk_protocols import gate_score


def _row(**values):
    return {
        "source": "АСТ00-00010",
        "decided": "2026-09-10",
        "text": "Подготовить справку",
        "owner": "Секретарь РК",
        "due": "2026-09-20",
        "status": "IN PROGRESS",
        **values,
    }


def _card(number: str = "АСТ00-00010", **values):
    return {
        "number": number,
        "date": "2026-09-10T18:00:00",
        "open": True,
        "status": "В работе",
        "topic": "Подготовить справку",
        "basis": "протокол ПСД_001_О_201",
        "due": "2026-09-20",
        "lines": [{"text": "Подготовить справку", "executor": "Секретарь РК", "due": "2026-09-20"}],
        "files": [{"created": "2026-09-16", "name": "справка.docx"}],
        **values,
    }


def test_classify_protocol_number_not_chair_role():
    assert classify_instruction("протокол ПСД_001_О_222 от 09.09.2026") == "sd"
    assert classify_instruction("План работ Ревизионной комиссии") == "rk"
    assert classify_instruction("поручение ПСД Амураль И.Б.") is None
    assert classify_instruction("директора по персоналу в РК") is None
    assert is_protocol_dump({"source": "ПСД_001_О_226"})
    assert not is_protocol_dump({"source": "АСТ00-00010"})


def test_within_24h_date_only_allows_next_day():
    from datetime import datetime

    decided = datetime(2026, 9, 10)
    assert within_24h(datetime(2026, 9, 11), decided, precise=False)
    assert not within_24h(datetime(2026, 9, 12), decided, precise=False)


def test_month_set_is_onec_protocols_and_assignments():
    report = score_instruction_kpi(
        [
            _row(source="АСТ00-00010"),
            _row(source="АСТ00-00011", decided="2026-09-12"),
            {"source": "ПСД_001_О_201", "Дата решения": "2026-09-10", "Поручение (результат/артефакт)": "протокол СД"},
        ],
        [
            _card("АСТ00-00010"),
            _card(
                "АСТ00-00011",
                date="2026-09-12",
                files=[{"created": "2026-09-15", "name": "отчёт.pdf"}],
            ),
        ],
        [{"number": "ПСД_001_О_201", "date": "2026-09-10", "status": "Закрыт"}],
        as_of=date(2026, 9, 16),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert report["r_total"] == 3
    assert report["r_in_tracker"] == 3
    assert report["r24"] == 3
    assert report["r_active"] == 2
    assert report["r_control"] == 2
    assert report["fact_pct"] == 100
    assert report["score_pct"] == 100


def test_missing_from_excel_stays_in_denominator():
    report = score_instruction_kpi(
        [_row(source="АСТ00-00010")],
        [_card("АСТ00-00010"), _card("АСТ00-00099", date="2026-09-08")],
        [{"number": "ПСД_001_О_220", "date": "2026-09-05"}],
        as_of=date(2026, 9, 16),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    by_number = {row["number"]: row for row in report["rows"] if row["in_period"]}
    assert report["r_total"] == 3
    assert report["r_in_tracker"] == 1
    assert by_number["АСТ00-00099"]["in_tracker"] is False
    assert by_number["АСТ00-00099"]["on_time"] is False
    assert by_number["ПСД_001_О_220"]["in_tracker"] is False
    assert by_number["ПСД_001_О_220"]["on_time"] is False
    assert report["r24"] == 1


def test_incomplete_assignment_in_excel_is_not_r24():
    report = score_instruction_kpi(
        [_row(source="АСТ00-00010", owner="", due="")],
        [_card("АСТ00-00010", due="", lines=[{"text": "Справка", "executor": "", "due": ""}])],
        [],
        as_of=date(2026, 9, 16),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert report["r_total"] == 1
    assert report["r_in_tracker"] == 1
    assert report["rows"][0]["complete"] is False
    assert report["r24"] == 0


def test_august_assignment_not_in_september_total():
    report = score_instruction_kpi(
        [_row(source="АСТ00-00012", decided="2026-08-20")],
        [_card("АСТ00-00012", date="2026-08-20", files=[])],
        [],
        as_of=date(2026, 9, 16),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    assert report["r_total"] == 0
    assert report["r_active"] == 1
    assert report["kpi3_1_pct"] is None
    assert report["kpi3_2_pct"] == 0.0
    assert report["fact_pct"] == 0.0


def test_control_from_weekly_report_not_from_bare_link():
    report = score_instruction_kpi(
        [
            _row(source="АСТ00-00010", evidence="\\\\share\\file.docx"),
            _row(source="АСТ00-00011"),
        ],
        [
            _card("АСТ00-00010", files=[]),
            _card("АСТ00-00011", files=[], weekly_report_date="2026-09-15"),
        ],
        as_of=date(2026, 9, 16),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
    )
    by_number = {row["number"]: row for row in report["rows"]}
    assert by_number["АСТ00-00010"]["control"] is False
    assert by_number["АСТ00-00011"]["control"] is True
    assert report["r_control"] == 1
    assert report["r_active"] == 2


def test_gate_on_min():
    assert gate_score(95) == 100
    assert gate_score(80) == 84.2


def test_compute_tile_update_uses_same_module():
    update = compute_tile_update(
        as_of=date(2026, 9, 16),
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 30),
        tracker=[
            _row(source="АСТ00-00010"),
            {"source": "ПСД_001_О_201", "Дата решения": "2026-09-10"},
        ],
        cards=[_card("АСТ00-00010")],
        protocols=[{"number": "ПСД_001_О_201", "date": "2026-09-10"}],
    )
    assert update["id"] == "instructions"
    assert update["fact"]["value"] == 100
    assert update["score_percent"] == 100
    assert "KPI3.1" in update["evidence"]


def test_load_tracker_json(tmp_path):
    path = tmp_path / "rows.json"
    path.write_text('[{"source": "АСТ00-00010", "Дата решения": "2026-09-10"}]', encoding="utf-8")
    rows = load_tracker(path)
    assert rows[0]["source"] == "АСТ00-00010"
