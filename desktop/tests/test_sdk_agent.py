from __future__ import annotations

from pathlib import Path

from app.api_client import WorkflowPlan, WorkflowPlanStep, WorkflowRecord
from app.sdk_agent.bridge import DEFAULT_SDK_MODEL, CursorSdkBridge, CursorSdkUnavailable
from app.sdk_agent.prompt import build_demo_sdk_prompt, build_design_sdk_prompt, build_sdk_prompt
from app.sdk_agent.tool_adapter import is_ask_question, sdk_tool_specs
from app.ui.pages.workflow_page import (
    _answered_text_for,
    _event_json,
    _keep_newer_phase,
    apply_sdk_answers_to_draft,
    qa_from_sdk_events,
    split_design_questions,
)
from app.ui.widgets.cursor_feed import resolve_feed_kind


def test_sdk_prompt_contains_plan_and_tool_instruction() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="done",
        plan=WorkflowPlan(
            goal="Проверять сроки проектов",
            constraints=["Не менять данные без подтверждения"],
            steps=[
                WorkflowPlanStep(
                    id="s1",
                    title="Собрать данные",
                    action="Прочитать проекты TurboProject",
                    done_when="Есть список проектов",
                )
            ],
        ),
    )
    prompt = build_sdk_prompt(record, "проверь сейчас")
    assert "Вызывай настоящий tool" in prompt
    assert "Проверять сроки проектов" in prompt
    assert "Прочитать проекты TurboProject" in prompt
    assert "проверь сейчас" in prompt


def test_demo_sdk_prompt_requires_playbook_and_tests() -> None:
    record = WorkflowRecord(
        id="wf-1",
        title="Контроль сроков",
        phase="designed",
        plan=WorkflowPlan(goal="Проверять сроки проектов"),
    )
    prompt = build_demo_sdk_prompt(record)
    assert "пробный прогон" in prompt
    assert "TESTS: PASS" in prompt
    assert "playbook" in prompt


def test_design_sdk_prompt_wraps_backend_design_prompt() -> None:
    record = WorkflowRecord(id="wf-1", title="Контроль сроков", phase="new")
    prompt = build_design_sdk_prompt(record, "Верни ТОЛЬКО один JSON-объект")
    assert "локальный Cursor SDK агент" in prompt
    assert "customTools" in prompt
    assert "required_clarifications" in prompt
    assert "askQuestion" in prompt
    assert "не ищи его в MCP" in prompt
    assert "QUESTION:" not in prompt
    assert "web_search" in prompt
    assert "Верни ТОЛЬКО один JSON-объект" in prompt
    assert "не пиши, что MCP не найден" in prompt


def test_run_sdk_prompt_lists_constructor_tools() -> None:
    record = WorkflowRecord(id="wf-1", title="Контроль сроков", phase="done")
    prompt = build_sdk_prompt(record, "проверь сейчас")
    assert "custom-user-tools" in prompt
    assert "web_search" in prompt


def test_sdk_event_json_parses_structured_payload() -> None:
    payload = _event_json('{"type":"question","question":"Когда запускать?","options":["ежедневно"]}')
    assert payload["type"] == "question"
    assert payload["question"] == "Когда запускать?"
    assert payload["options"] == ["ежедневно"]


def test_sdk_answers_close_matching_clarifications() -> None:
    draft = apply_sdk_answers_to_draft(
        {
            "required_clarifications": [
                {
                    "question": "Когда запускать агент?",
                    "options": ["ежедневно", "вручную"],
                },
                {
                    "question": "Кто получает отчёт?",
                    "options": ["руководитель", "куратор"],
                },
            ],
            "recipient": "",
        },
        [
            ("Когда запускать агент?", "ежедневно утром"),
            ("Кто получает отчёт?", "руководитель проекта"),
        ],
    )
    assert draft["required_clarifications"] == []
    assert "ежедневно утром" in draft["answers"]
    assert draft["when_to_run"] == "ежедневно утром"
    assert draft["recipient"] == "руководитель проекта"

    rewritten = apply_sdk_answers_to_draft(
        {
            "required_clarifications": [
                {
                    "question": "Как часто стартовать этого агента?",
                    "options": ["каждый час", "вручную"],
                }
            ]
        },
        [("Когда запускать агент?", "только вручную из чата")],
    )
    assert rewritten["required_clarifications"] == []


def test_split_design_questions_breaks_numbered_bundle() -> None:
    parts = split_design_questions(
        "\n".join(
            [
                "Нужны ответы:",
                "1. Когда запускать агент?",
                "- ежедневно утром",
                "- только вручную",
                "2. Какой период и контур проектов проверять за один прогон?",
                "- все активные",
                "- вехи на 7 дней",
                "3. Кто получает отчёт?",
                "- руководитель",
            ]
        )
    )
    assert [item[0] for item in parts] == [
        "Когда запускать агент?",
        "Какой период и контур проектов проверять за один прогон?",
        "Кто получает отчёт?",
    ]
    assert parts[0][1] == ["ежедневно утром", "только вручную"]


def test_rephrased_question_reuses_previous_answer() -> None:
    qa = [("Когда запускать агент?", "только вручную из чата")]
    assert _answered_text_for(qa, "Как часто стартовать этого агента?") == "только вручную из чата"


def test_qa_from_sdk_events_pairs_question_and_answer() -> None:
    pairs = qa_from_sdk_events(
        [
            {
                "type": "question",
                "requestId": "r1",
                "question": "Когда запускать агент?",
            },
            {
                "type": "tool_result",
                "requestId": "r1",
                "tool": "askQuestion",
                "result": {"answer": "вручную"},
            },
        ]
    )
    assert pairs == [("Когда запускать агент?", "вручную")]


def test_question_feed_kind_is_separate_block() -> None:
    assert resolve_feed_kind(title="Уточнение") == "question"
    assert resolve_feed_kind(kind="question") == "question"


def test_sdk_tool_specs_include_desktop_schema() -> None:
    tools = sdk_tool_specs()
    names = {str(item.get("name") or "") for item in tools}
    assert "askQuestion" in names
    assert "web_search" in names
    ask = next(item for item in tools if item.get("name") == "askQuestion")
    assert "question" in (ask.get("inputSchema") or {}).get("properties", {})
    web = next(item for item in tools if item.get("name") == "web_search")
    assert isinstance(web.get("inputSchema"), dict)


def test_keep_newer_phase_does_not_fall_back_to_document() -> None:
    designed = WorkflowRecord(id="wf-1", title="Агент", phase="designed")
    saved = WorkflowRecord(id="wf-1", title="Агент", phase="document")
    kept = _keep_newer_phase(designed, saved)
    assert kept.phase == "designed"


def test_is_ask_question_name() -> None:
    assert is_ask_question("askQuestion")
    assert is_ask_question("ask_question")
    assert not is_ask_question("web_search")


def test_bridge_reports_missing_api_key(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    runner = tmp_path / "runner.ts"
    runner.write_text("", encoding="utf-8")
    bridge = CursorSdkBridge(runner=runner)
    try:
        bridge.check_ready()
    except CursorSdkUnavailable as exc:
        assert "CURSOR_API_KEY" in str(exc)
    else:
        raise AssertionError("expected CursorSdkUnavailable")


def test_node_version_parser() -> None:
    assert CursorSdkBridge._node_version("22.13.0") == (22, 13)
    assert CursorSdkBridge._node_version("bad") == (0, 0)


def test_default_sdk_model_is_grok_46() -> None:
    assert DEFAULT_SDK_MODEL == "grok-4.6"
