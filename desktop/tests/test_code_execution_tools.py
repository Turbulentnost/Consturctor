from __future__ import annotations

from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspaceResolver
from app.tools.ac.code_execution_tools import CodeRunPythonTool


def test_run_python_script_that_reads_stdin_finishes(tmp_path: Path) -> None:
    tool = CodeRunPythonTool(AgentWorkspaceResolver(tmp_path))
    result = tool.execute(
        {
            "workflow_id": "wf-py",
            "filename": "echo_stdin.py",
            "code": "import sys\nprint(sys.stdin.read() or 'eof')\n",
            "timeout_seconds": 10,
        }
    )
    assert result.ok is True
    assert result.error_type is None
    assert result.output_data.get("timed_out") is False
    assert "eof" in str(result.output_data.get("stdout") or "")


def test_run_python_ignores_parent_pythonpath(
    tmp_path: Path, monkeypatch
) -> None:
    poison = tmp_path / "poison"
    poison.mkdir()
    (poison / "json.py").write_text(
        "raise SystemExit('leaked PYTHONPATH')\n", encoding="utf-8"
    )
    monkeypatch.setenv("PYTHONPATH", str(poison))
    tool = CodeRunPythonTool(AgentWorkspaceResolver(tmp_path))
    result = tool.execute(
        {
            "workflow_id": "wf-py",
            "filename": "use_json.py",
            "code": "import json\nprint(json.dumps({'ok': True}))\n",
            "timeout_seconds": 10,
        }
    )
    assert result.ok is True
    assert "leaked PYTHONPATH" not in str(result.output_data.get("stderr") or "")
    assert "ok" in str(result.output_data.get("stdout") or "")
