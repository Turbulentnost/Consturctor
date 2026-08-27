from app.schemas.regulation import RegulationFragment, RegulationParseResult
from app.services.regulation_functions.service import (
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
    assert not _has_functions({"functions": [], "questions": [{"id": "q1"}]})


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
