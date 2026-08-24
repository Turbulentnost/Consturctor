from __future__ import annotations

from pathlib import Path

from app.api_client import WorkflowPlan, WorkflowPlanStep, WorkflowRecord
from app.sdk_agent.bridge import DEFAULT_SDK_MODEL, CursorSdkBridge, CursorSdkUnavailable
from app.sdk_agent.prompt import build_demo_sdk_prompt, build_design_sdk_prompt, build_sdk_prompt
from app.sdk_agent.tool_adapter import sdk_tool_specs


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
    assert "Сформируй план достижения цели" in prompt
    assert "Верни ТОЛЬКО один JSON-объект" in prompt


def test_sdk_tool_specs_include_desktop_schema() -> None:
    tools = sdk_tool_specs()
    names = {str(item.get("name") or "") for item in tools}
    assert "web_search" in names
    web = next(item for item in tools if item.get("name") == "web_search")
    assert isinstance(web.get("inputSchema"), dict)


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
