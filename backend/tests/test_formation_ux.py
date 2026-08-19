from app.schemas.trigger import ScheduleTriggerSpec
from app.services.workflows.cursor_tools import (
    _format_tool_output,
    _tool_cache_key,
    is_directory_search_query,
    normalize_users_list_query,
)
from app.services.workflows.prompts import (
    parse_playbook_from_text,
    parse_work_result,
    title_from_materials,
)
from app.services.workflows.schedule_draft import draft_after_demo, trigger_chip_label


def test_title_from_passport_header() -> None:
    notes = (
        "# Паспорт ИИ-агента: ИИ-агент: контролирует сроки, качество и риски проектов\n"
        "Составь план реализации.\n"
    )
    assert title_from_materials(notes=notes, document_name="notes.txt") == (
        "контролирует сроки, качество и риски проектов"
    )


def test_title_ignores_notes_filename() -> None:
    assert title_from_materials(notes="", document_name="notes.txt") == "ИИ-агент"


def test_parse_work_result_block() -> None:
    text = """
CLARIFY leftover
RESULT:
Нашёл 2 просрочки в проекте Альфа и отправил сводку руководителю.
FILES:
- C:/out/report.xlsx
ACTIONS:
- собрал сводку
NOTIFICATIONS:
- Мангасарян Давид
SCHEDULE:
- каждые 15 мин
"""
    work = parse_work_result(text)
    assert "просрочки" in work["text"]
    assert work["files"][0].endswith("report.xlsx")
    assert work["actions"]
    assert work["notifications"]
    assert work["schedule"] == ["каждые 15 мин"]


def test_users_list_ignores_generic_query() -> None:
    assert not is_directory_search_query("получатель")
    assert not is_directory_search_query("все")
    assert not is_directory_search_query("ab")
    search, ignored = normalize_users_list_query({"query": "получатели"})
    assert search == ""
    assert ignored == "получатели"
    assert is_directory_search_query("Мангасарян Давид")
    assert is_directory_search_query("user@example.com")


def test_format_tool_output_empty_users() -> None:
    text = _format_tool_output("users.list", {"users": [], "count": 0})
    assert "0" in text
    assert "пользовател" in text
    assert "{" not in text


def test_tool_cache_key_normalizes_junk_users_query() -> None:
    a = _tool_cache_key("users.list", {"query": "получатель", "workflow_id": "w1"})
    b = _tool_cache_key("users.list", {"search": "все"})
    c = _tool_cache_key("users.list", {})
    assert a == b == c


def test_chip_labels() -> None:
    assert trigger_chip_label(
        ScheduleTriggerSpec(kind="interval", interval_value=15, interval_unit="minutes")
    ) == "каждые 15 мин"
    assert trigger_chip_label(
        ScheduleTriggerSpec(kind="datetime", at="12:00", once=False)
    ) == "ежедневно в 12:00"
    assert trigger_chip_label(
        ScheduleTriggerSpec(kind="event", condition="нарушение SLA")
    ).startswith("при событии")


def test_draft_after_demo_from_playbook() -> None:
    draft = draft_after_demo(
        title="notes.txt",
        notes="# Паспорт ИИ-агента: Контроль сроков проектов\nТриггер: каждые 15 минут\n",
        playbook={
            "name": "Контроль сроков проектов",
            "expected_result": "сводка руководителю",
            "triggers": [
                {"kind": "interval", "interval_value": 15, "interval_unit": "minutes"}
            ],
        },
        work={"schedule": []},
    )
    assert draft.name == "Контроль сроков проектов"
    assert draft.triggers
    assert trigger_chip_label(draft.triggers[0]) == "каждые 15 мин"


def test_playbook_parse_name_and_triggers() -> None:
    parsed = parse_playbook_from_text(
        """
```json
{
  "name": "Контроль сроков",
  "instructions": "Читай проекты и пиши сводку.",
  "example_run": "Вызвал turboproject.",
  "expected_result": "текст сводки",
  "triggers": [{"kind": "interval", "interval_value": 15, "interval_unit": "minutes"}]
}
```
"""
    )
    assert parsed["name"] == "Контроль сроков"
    assert parsed["expected_result"] == "текст сводки"
    assert parsed["triggers"]
