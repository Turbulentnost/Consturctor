from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.agent_kpi import (
    NO_RUNS_LABEL,
    apply_facts,
    build_kpi_record,
    compute_fact,
    interval_minutes,
    parse_kpi_payload,
)
from app.services.workflows.prompts import build_kpi_curator_prompt


def _run(*, status: str, source: str = "chat", minutes_ago: float = 0) -> SimpleNamespace:
    started = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=minutes_ago)
    return SimpleNamespace(status=status, source=source, started_at=started, finished_at=started)


def test_interval_minutes_from_hours_trigger() -> None:
    schedule = {"triggers": [{"kind": "interval", "interval_value": 2, "interval_unit": "hours"}]}
    assert interval_minutes(schedule) == 120


def test_default_kpi_has_plan_and_null_facts() -> None:
    schedule = {"triggers": [{"kind": "interval", "interval_value": 30, "interval_unit": "minutes"}]}
    kpi = build_kpi_record(None, title="Контроль сроков", goal="следить за сроками", schedule=schedule)
    kinds = [tile["measure"]["kind"] for tile in kpi["tiles"]]
    assert "expected_interval" in kinds
    assert "on_schedule_rate" in kinds
    assert all(tile["fact"]["value"] is None for tile in kpi["tiles"])
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
      "measure": {"kind": "success_rate", "params": {}, "formula": "ok/all"}
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


def test_facts_empty_runs_stay_null() -> None:
    schedule = {"triggers": [{"kind": "interval", "interval_value": 1, "interval_unit": "hours"}]}
    kpi = build_kpi_record(None, title="A", goal="B", schedule=schedule)
    applied = apply_facts(kpi, [], schedule)
    assert all(tile["fact"]["value"] is None for tile in applied["tiles"])
    value, hint = compute_fact("success_rate", {}, [], schedule)
    assert value is None
    assert hint == NO_RUNS_LABEL


def test_success_and_fail_from_runs() -> None:
    runs = [_run(status="ok"), _run(status="ok"), _run(status="error")]
    assert compute_fact("success_rate", {}, runs, {}) == (66.7, "доля успешных")
    assert compute_fact("fail_count", {}, runs, {}) == (1.0, "ошибки")
    assert compute_fact("runs_count", {}, runs, {}) == (3.0, "число прогонов")


def test_on_schedule_rate_from_trigger_gaps() -> None:
    schedule = {"triggers": [{"kind": "interval", "interval_value": 60, "interval_unit": "minutes"}]}
    runs = [
        _run(status="ok", source="trigger", minutes_ago=120),
        _run(status="ok", source="trigger", minutes_ago=60),
        _run(status="ok", source="trigger", minutes_ago=0),
    ]
    value, _hint = compute_fact("on_schedule_rate", {}, runs, schedule)
    assert value == 100.0
    interval, _ = compute_fact("expected_interval", {}, runs, schedule)
    assert interval == 60.0


def test_curator_prompt_lists_kinds() -> None:
    prompt = build_kpi_curator_prompt(
        title="Контроль сроков",
        goal="не пропускать дедлайны",
        plan_text="Шаг 1",
        schedule_draft={"triggers": [{"kind": "interval", "interval_value": 1, "interval_unit": "hours"}]},
    )
    assert "on_schedule_rate" in prompt
    assert "constructor_tool" in prompt
    assert "JSON" in prompt
