from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.tools.ac.agent_workspace import AgentWorkspaceResolver
from app.tools.ac.closure_check_tool import (
    ClosureCheckTool,
    clear_closure_check,
    closure_check_block,
    load_closure_check,
)

ROOT = Path(__file__).resolve().parents[2]
ORCH_SIDECAR = ROOT / "orchestrator" / "desktop-electron" / "pybridge" / "agent_sidecar.py"


def _assignment(number: str, conclusion: str = "Нельзя закрыть — нет оснований") -> dict:
    return {
        "number": number,
        "target_id": "cb1131b8-c85c-11f1-98a3-6cb31113810e",
        "conclusion": conclusion,
        "done": 0,
        "total": 1,
        "tasks": [{"n": 1, "performer": "Тен Л.Л.", "conclusion": "Не выполнено"}],
    }


def _call(tool: ClosureCheckTool, *items: dict):
    return tool.execute({"agent_id": "wf-1", "assignments": list(items)})


def test_batches_accumulate_and_repeat_replaces(tmp_path: Path) -> None:
    tool = ClosureCheckTool(AgentWorkspaceResolver(tmp_path))

    first = _call(tool, _assignment("АСТ00-00113"), _assignment("АСТ00-00111"))
    second = _call(tool, _assignment("АСТ00-00109"), _assignment("АСТ00-00113", "Можно закрыть"))

    assert first.ok and second.ok
    assert second.output_data["numbers"] == ["АСТ00-00113", "АСТ00-00111", "АСТ00-00109"]
    assert load_closure_check(tmp_path / "wf-1")[0]["conclusion"] == "Можно закрыть"


def test_empty_call_fails(tmp_path: Path) -> None:
    result = ClosureCheckTool(AgentWorkspaceResolver(tmp_path)).execute({"agent_id": "wf-1", "assignments": []})

    assert not result.ok


def test_block_parses_as_registry_json(tmp_path: Path) -> None:
    _call(ClosureCheckTool(AgentWorkspaceResolver(tmp_path)), _assignment("АСТ00-00113"))

    block = closure_check_block(tmp_path / "wf-1")
    body = re.match(r"```closure-check\n([\s\S]*)\n```$", block)

    assert body is not None
    assert json.loads(body.group(1))["assignments"][0]["number"] == "АСТ00-00113"


def test_clear_drops_previous_run(tmp_path: Path) -> None:
    _call(ClosureCheckTool(AgentWorkspaceResolver(tmp_path)), _assignment("АСТ00-00113"))

    clear_closure_check(tmp_path / "wf-1")

    assert closure_check_block(tmp_path / "wf-1") == ""


@pytest.fixture(scope="module")
def orch_sidecar():
    spec = importlib.util.spec_from_file_location("orch_agent_sidecar", ORCH_SIDECAR)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ORCH_SIDECAR.parent))
    spec.loader.exec_module(module)
    return module


def test_sidecar_replaces_model_block_with_saved(tmp_path: Path, orch_sidecar) -> None:
    _call(ClosureCheckTool(AgentWorkspaceResolver(tmp_path)), _assignment("АСТ00-00113"))
    answer = '## WORK_RESULT\nИтог.\n\n```closure-check\n{"assignments":[{"number":"СТАРЫЙ"}]}\n```\n'

    merged = orch_sidecar._with_closure_check(answer, str(tmp_path / "wf-1"))

    assert "СТАРЫЙ" not in merged
    assert merged.startswith("## WORK_RESULT\nИтог.")
    assert merged.count("```closure-check") == 1
    assert "АСТ00-00113" in merged


def test_sidecar_keeps_answer_without_saved_verdicts(tmp_path: Path, orch_sidecar) -> None:
    assert orch_sidecar._with_closure_check("ответ", str(tmp_path / "wf-1")) == "ответ"


def test_playbook_model_params_override(orch_sidecar) -> None:
    import inspect

    record = SimpleNamespace(
        local_run={"playbook": {"model_params": [{"id": "reasoning_effort", "value": "high"}, {"id": "", "value": "x"}]}}
    )

    assert orch_sidecar._workflow_model_params(record) == [{"id": "reasoning_effort", "value": "high"}]
    assert orch_sidecar._workflow_model_params(SimpleNamespace(local_run={"playbook": {}})) is None
    assert "model_params" in inspect.signature(orch_sidecar.ElectronBridge.run).parameters
