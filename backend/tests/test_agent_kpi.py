from datetime import datetime, timedelta, timezone

from app.services.agent_kpi import (
    MIN_INTERVAL_SECONDS,
    apply_calc_updates,
    build_kpi_record,
    interval_minutes,
    is_tile_due,
    normalize_method,
    parse_calc_payload,
    parse_kpi_payload,
    tile_color,
    advance_next_run_at,
)
from app.services.workflows.prompts import build_kpi_calc_prompt, build_kpi_curator_prompt


def test_interval_minutes_from_hours_trigger() -> None:
    schedule = {"triggers": [{"kind": "interval", "interval_value": 2, "interval_unit": "hours"}]}
    assert interval_minutes(schedule) == 120


def test_default_kpi_has_method_and_null_facts() -> None:
    schedule = {"triggers": [{"kind": "interval", "interval_value": 30, "interval_unit": "minutes"}]}
    kpi = build_kpi_record(None, title="Контроль сроков", goal="следить за сроками", schedule=schedule)
    kinds = [tile["measure"]["kind"] for tile in kpi["tiles"]]
    assert "expected_interval" in kinds
    assert "on_schedule_rate" in kinds
    assert all(tile["fact"]["value"] is None for tile in kpi["tiles"])
    assert all(tile["score_percent"] is None for tile in kpi["tiles"])
    assert all(tile["color"] == "none" for tile in kpi["tiles"])
    assert all(tile["method"]["how"] for tile in kpi["tiles"])
    assert all(tile["method"]["plan_explanation"] for tile in kpi["tiles"])
    assert all(tile["method"]["fact_explanation"] for tile in kpi["tiles"])
    assert all(tile["method"]["score_explanation"] for tile in kpi["tiles"])
    assert all(tile["method"]["system"] for tile in kpi["tiles"])
    assert all(tile["next_run_at"] for tile in kpi["tiles"])
    assert "должен" in kpi["summary"].casefold() or "запускаться" in kpi["summary"].casefold()


def test_parse_kpi_json_and_ignore_unknown_kind() -> None:
    text = """
```json
{
  "summary": "Раз в час проверять сроки",
  "tiles": [
    {
      "id": "ok_rate",
      "name": "Успешность",
      "plan": {"label": "План", "value": 100, "unit": "%", "description": "без ошибок"},
      "fact": {"label": "Факт", "value": 12, "unit": "%", "description": "ok/all"},
      "measure": {"kind": "success_rate", "params": {}, "formula": "ok/all"},
      "method": {
        "how": "ok / all",
        "when": "каждый час",
        "plan_update": "раз в неделю",
        "fact_update": "каждый час",
        "percent_formula": "факт",
        "plan_explanation": "План — все запуски без ошибки.",
        "fact_explanation": "Факт — доля успешных запусков.",
        "score_explanation": "Оценка совпадает с фактом.",
        "system": "success = ok / (ok + error)",
        "green_min": 95,
        "yellow_min": 80,
        "schedule": {"kind": "interval", "interval_seconds": 3600}
      }
    },
    {
      "id": "tp",
      "name": "Поля TurboProject",
      "plan": {"value": 1},
      "fact": {"value": null},
      "measure": {"kind": "turboproject_fields"}
    }
  ]
}
```
"""
    parsed = parse_kpi_payload(text)
    kpi = build_kpi_record(parsed, title="A", goal="B", schedule={})
    assert kpi["summary"] == "Раз в час проверять сроки"
    assert [tile["measure"]["kind"] for tile in kpi["tiles"]] == ["success_rate"]
    assert kpi["tiles"][0]["fact"]["value"] is None
    assert kpi["tiles"][0]["method"]["green_min"] == 95
    assert kpi["tiles"][0]["method"]["yellow_min"] == 80
    assert kpi["tiles"][0]["method"]["how"] == "ok / all"
    assert kpi["tiles"][0]["method"]["plan_explanation"] == "План — все запуски без ошибки."
    assert kpi["tiles"][0]["method"]["system"] == "success = ok / (ok + error)"


def test_normalize_method_thresholds_and_min_interval() -> None:
    method = normalize_method(
        {"green_min": 80, "yellow_min": 90, "schedule": {"kind": "interval", "interval_seconds": 30}},
        kind="success_rate",
    )
    assert method["yellow_min"] < method["green_min"]
    assert method["schedule"]["interval_seconds"] == MIN_INTERVAL_SECONDS
    assert method["how"]
    assert method["plan_explanation"]
    assert method["fact_explanation"]
    assert method["score_explanation"]
    assert method["system"]
    assert "×" not in method["plan_explanation"]
    assert "Δ" not in method["fact_explanation"]


def test_tile_color_bands() -> None:
    assert tile_color(95, 90, 70) == "green"
    assert tile_color(75, 90, 70) == "yellow"
    assert tile_color(40, 90, 70) == "red"
    assert tile_color(None, 90, 70) == "none"


def test_next_run_at_interval_and_at() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    interval = normalize_method({"schedule": {"kind": "interval", "interval_seconds": 600}})
    nxt = advance_next_run_at(interval, now=now)
    assert nxt.startswith("2026-08-18T12:10")
    at_method = normalize_method({"schedule": {"kind": "at", "at": "2026-08-18T15:00:00+00:00"}})
    assert advance_next_run_at(at_method, now=now) == ""
    retry = advance_next_run_at(interval, now=now, failed=True, failures=1)
    assert retry.startswith("2026-08-18T12:02")


def test_is_tile_due_missing_next_run() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    assert is_tile_due({"id": "a"}, now) is True
    assert is_tile_due({"id": "a", "updated_at": now.isoformat()}, now) is False
    assert is_tile_due({"id": "a", "next_run_at": (now - timedelta(minutes=1)).isoformat()}, now) is True
    assert is_tile_due({"id": "a", "next_run_at": (now + timedelta(hours=1)).isoformat()}, now) is False


def test_apply_calc_updates_only_due_tiles() -> None:
    schedule = {"triggers": [{"kind": "interval", "interval_value": 1, "interval_unit": "hours"}]}
    kpi = build_kpi_record(None, title="A", goal="B", schedule=schedule)
    first_id = kpi["tiles"][0]["id"]
    second_id = kpi["tiles"][1]["id"]
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    applied = apply_calc_updates(
        kpi,
        [
            {
                "id": first_id,
                "fact": {"value": 80, "unit": "%"},
                "score_percent": 80,
                "evidence": "3 прогона ok из 4",
            },
            {"id": "unknown", "fact": {"value": 1}, "score_percent": 1},
        ],
        due_ids={first_id, second_id},
        now=now,
    )
    by_id = {tile["id"]: tile for tile in applied["tiles"]}
    assert by_id[first_id]["fact"]["value"] == 80
    assert by_id[first_id]["score_percent"] == 80
    assert by_id[first_id]["color"] == "yellow"
    assert by_id[first_id]["updated_at"] == now.isoformat()
    assert by_id[first_id]["evidence"] == "3 прогона ok из 4"
    assert by_id[second_id]["fact"]["value"] is None
    assert by_id[second_id]["calc_failures"] == 1


def test_apply_calc_empty_evidence_when_no_runs() -> None:
    kpi = build_kpi_record(None, title="A", goal="B", schedule={})
    tile_id = kpi["tiles"][0]["id"]
    applied = apply_calc_updates(
        kpi,
        [{"id": tile_id, "fact": {"value": None}, "score_percent": None}],
        due_ids={tile_id},
    )
    assert applied["tiles"][0]["evidence"] == "ещё нет прогонов"


def test_parse_calc_payload() -> None:
    text = """
```json
{"tiles": [{"id": "success_rate", "fact": {"value": 100}, "score_percent": 100, "evidence": "2 ok"}]}
```
"""
    parsed = parse_calc_payload(text)
    assert parsed[0]["id"] == "success_rate"
    assert parsed[0]["score_percent"] == 100
    assert parsed[0]["evidence"] == "2 ok"


def test_preserve_runtime_keeps_fact_and_score() -> None:
    stored = {
        "summary": "ok",
        "tiles": [
            {
                "id": "success_rate",
                "name": "Успешность",
                "plan": {"value": 100, "unit": "%"},
                "fact": {"value": 66.7, "unit": "%"},
                "measure": {"kind": "success_rate"},
                "score_percent": 66.7,
                "evidence": "2 ok + 1 error",
                "updated_at": "2026-08-18T12:00:00+00:00",
                "next_run_at": "2026-08-18T13:00:00+00:00",
                "method": {"how": "ok/all", "green_min": 90, "yellow_min": 70},
            }
        ],
    }
    kpi = build_kpi_record(stored, title="A", goal="B", schedule={}, preserve_runtime=True)
    tile = kpi["tiles"][0]
    assert tile["fact"]["value"] == 66.7
    assert tile["score_percent"] == 66.7
    assert tile["color"] == "red"
    assert tile["next_run_at"] == "2026-08-18T13:00:00+00:00"
    assert tile["evidence"] == "2 ok + 1 error"


def test_curator_prompt_requires_method_and_thresholds() -> None:
    prompt = build_kpi_curator_prompt(
        title="Контроль сроков",
        goal="не пропускать дедлайны",
        plan_text="Шаг 1",
        schedule_draft={"triggers": [{"kind": "interval", "interval_value": 1, "interval_unit": "hours"}]},
    )
    assert "method" in prompt
    assert "plan_explanation" in prompt
    assert "fact_explanation" in prompt
    assert "score_explanation" in prompt
    assert "system" in prompt
    assert "простыми словами" in prompt
    assert "green_min" in prompt
    assert "yellow_min" in prompt
    assert "on_schedule_rate" in prompt
    assert "constructor_tool" in prompt
    assert "JSON" in prompt


def test_calc_prompt_includes_runs_and_method() -> None:
    prompt = build_kpi_calc_prompt(
        title="A",
        goal="B",
        plan_text="Шаг 1",
        tiles=[{"id": "success_rate", "method": {"how": "ok/all"}}],
        runs=[{"id": "r1", "status": "ok", "answer": "готово"}],
    )
    assert "success_rate" in prompt
    assert "score_percent" in prompt
    assert "evidence" in prompt
    assert "готово" in prompt
    assert "plan_explanation" in prompt
    assert "не используй" in prompt
