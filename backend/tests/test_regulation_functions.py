from app.schemas.regulation import RegulationFragment, RegulationParseResult
from app.services.regulation_creation.interview import process_extraction_model_rules
from app.services.regulation_functions.service import (
    _build_prompt,
    _function_belongs_to_position,
    _has_functions,
    _map_agent_result,
    functions_from_questions,
)


def _fragment(fragment_id: str, text: str) -> RegulationFragment:
    return RegulationFragment(fragmentId=fragment_id, page=1, section="1", text=text)


def _regulation() -> RegulationParseResult:
    return RegulationParseResult(
        regulationId="reg-1",
        fileName="reg.docx",
        fragments=[
            _fragment("reg-1-B-1", "Сводный Excel-календарь залов — рабочий артефакт аппарата ПСД.")
        ],
    )


def test_functions_from_questions_rebuilds_blocks() -> None:
    recovered = functions_from_questions(
        [
            {
                "functionId": "f11",
                "context": "Сводный план совещаний. Пересчёт каждый день.",
                "sourceRefs": [{"fragmentId": "reg-1-B-1", "quote": "Excel-календарь"}],
            },
            {
                "functionId": "f11",
                "text": "Как часто пересчитываете план?",
                "relatedFunctionIds": ["f12"],
            },
        ]
    )
    assert len(recovered) == 1
    assert recovered[0]["id"] == "f11"
    assert "Сводный план" in recovered[0]["title"]
    assert recovered[0]["relatedFunctionIds"] == ["f12"]


def test_map_keeps_recovered_functions() -> None:
    recovered = functions_from_questions(
        [
            {
                "functionId": "f11",
                "context": "Сводный план совещаний без коллизий.",
                "sourceRefs": [{"fragmentId": "reg-1-B-1"}],
            }
        ]
    )
    recovered[0]["actor"] = "Помощник Председателя совета директоров"
    mapped = _map_agent_result(
        {"functions": recovered, "questions": []},
        regulation=_regulation(),
        regulation_id="reg-1",
        position="Помощник Председателя совета директоров",
        department="Управление делами",
        cursor_agent_id="agent-1",
        cursor_run_id="run-1",
    )
    assert mapped.functions
    assert mapped.functions[0].title.startswith("Сводный план")


def test_has_functions() -> None:
    assert _has_functions({"functions": [{"id": "f1"}]})
    assert _has_functions({"processes": [{"id": "f1", "title": "Контроль календаря ПСД"}]})
    assert not _has_functions({"functions": [], "questions": [{"id": "q1"}]})


def test_prompt_uses_interview_process_model() -> None:
    prompt = _build_prompt(
        _regulation(),
        position="Помощник Председателя совета директоров",
        department="Управление делами",
    )
    rules = process_extraction_model_rules(position="Помощник Председателя совета директоров")
    assert "processes" in prompt
    assert "knownFacts" in prompt
    assert rules in prompt
    assert "Не выделяй «Изменение календаря» отдельно" in prompt


def test_map_keeps_calendar_change_inside_control_process() -> None:
    mapped = _map_agent_result(
        {
            "processes": [
                {
                    "id": "f1",
                    "title": "Контроль календаря ПСД",
                    "actor": "Помощник Председателя совета директоров",
                    "roleStatus": "belongs",
                    "sourceRefs": [{"fragmentId": "reg-1-B-1", "quote": "контроль календаря ПСД"}],
                    "knownFacts": {
                        "workLocation": "Excel-календарь",
                        "steps": ["Проверяет сводный календарь"],
                    },
                },
                {
                    "id": "f2",
                    "title": "Изменение календаря",
                    "actor": "Помощник Председателя совета директоров",
                    "roleStatus": "belongs",
                    "sourceRefs": [{"fragmentId": "reg-1-B-1", "quote": "вносит изменения в календарь"}],
                    "knownFacts": {"steps": ["Вносит правки в календарь"]},
                },
            ],
            "functions": [],
            "questions": [],
        },
        regulation=_regulation(),
        regulation_id="reg-1",
        position="Помощник Председателя совета директоров",
        department="Управление делами",
        cursor_agent_id="agent-1",
        cursor_run_id="run-1",
    )
    assert len(mapped.functions) == 1
    assert mapped.functions[0].title == "Контроль календаря ПСД"
    step_texts = " ".join(item.description for item in mapped.functions[0].dependencies)
    assert "Изменение календаря" in step_texts or "Вносит правки" in step_texts
    assert len(mapped.documentMap.processes) == 1


def test_map_does_not_merge_unrelated_processes() -> None:
    mapped = _map_agent_result(
        {
            "functions": [
                {
                    "id": "f1",
                    "title": "Контроль календаря ПСД",
                    "actor": "Помощник Председателя совета директоров",
                    "sourceRefs": [{"fragmentId": "reg-1-B-1", "quote": "календарь ПСД"}],
                },
                {
                    "id": "f2",
                    "title": "Организация заседаний СД",
                    "actor": "Помощник Председателя совета директоров",
                    "sourceRefs": [{"fragmentId": "reg-1-B-1", "quote": "заседания СД"}],
                },
            ],
            "questions": [],
        },
        regulation=_regulation(),
        regulation_id="reg-1",
        position="Помощник Председателя совета директоров",
        department="Управление делами",
        cursor_agent_id="agent-1",
        cursor_run_id="run-1",
    )
    titles = {item.title for item in mapped.functions}
    assert titles == {"Контроль календаря ПСД", "Организация заседаний СД"}


def test_belongs_to_position_trusts_cursor_actor() -> None:
    assert _function_belongs_to_position(
        {
            "title": "Организация совещаний",
            "actor": "Помощник Председателя совета директоров",
            "sourceRefs": [{"fragmentId": "reg-1-B-1"}],
        },
        position_terms=["Помощник Председателя совета директоров", "Помощник ПСД"],
        fragments={"reg-1-B-1": _fragment("reg-1-B-1", "Сводный план совещаний")},
    )


def test_belongs_to_position_drops_foreign_actor() -> None:
    assert not _function_belongs_to_position(
        {
            "title": "Утверждение бюджета",
            "actor": "Руководитель сектора внедрения",
            "sourceRefs": [{"fragmentId": "reg-1-B-1"}],
        },
        position_terms=["Помощник Председателя совета директоров"],
        fragments={"reg-1-B-1": _fragment("reg-1-B-1", "утверждает руководитель сектора")},
    )
