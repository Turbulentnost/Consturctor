from app.services.workflows.prompts import parse_playbook_from_text
from app.services.workflows.service import playbook_of


def test_parse_playbook_from_json_fence() -> None:
    text = """
```json
{
  "instructions": "Читай проекты в TurboProject и пришли сводку.",
  "example_run": "Вызвал turboproject, нашёл 3 проекта, отправил список."
}
```
"""
    parsed = parse_playbook_from_text(text)
    assert "TurboProject" in parsed["instructions"]
    assert "turboproject" in parsed["example_run"]


def test_playbook_of_prefers_local_run() -> None:
    row = {
        "local_run": {
            "playbook": {
                "instructions": "из local",
                "example_run": "пример",
                "demo_ok": True,
            }
        },
        "plan_json": {"playbook": {"instructions": "из плана"}},
    }
    assert playbook_of(row)["instructions"] == "из local"


def test_playbook_of_falls_back_to_plan() -> None:
    row = {"local_run": {}, "plan_json": {"playbook": {"instructions": "из плана"}}}
    assert playbook_of(row)["instructions"] == "из плана"
