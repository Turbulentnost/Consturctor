from __future__ import annotations

from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspaceResolver
from app.tools.ac.code_execution_tools import (
    CodeRunPythonTool,
    CodeWritePythonTool,
    promote_kpi_artifacts,
)


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


def test_write_python_puts_kpi_module_next_to_tests(tmp_path: Path) -> None:
    tool = CodeWritePythonTool(AgentWorkspaceResolver(tmp_path))
    module = tool.execute(
        {
            "workflow_id": "wf-kpi",
            "filename": "generated/orders.py",
            "code": "def score_orders_kpi(rows, *, as_of, date_from=None, date_to=None):\n"
            "    return {'fact_pct': 100.0, 'score_pct': 100.0, 'contrib_pct': 50.0, 'rows': rows}\n",
        }
    )
    test = tool.execute(
        {
            "workflow_id": "wf-kpi",
            "filename": "tests/test_orders.py",
            "code": "def test_orders():\n"
            "    from generated.orders import score_orders_kpi\n"
            "    from datetime import date\n"
            "    report = score_orders_kpi([{'ok': True}], as_of=date(2026, 1, 1))\n"
            "    assert report['fact_pct'] == 100.0\n",
        }
    )
    root = tmp_path / "wf-kpi"
    assert module.ok is True
    assert test.ok is True
    assert (root / "generated" / "orders.py").is_file()
    assert (root / "tests" / "test_orders.py").is_file()
    assert not (root / "code" / "generated" / "orders.py").exists()

    misplaced = root / "code" / "generated" / "orders.py"
    misplaced.parent.mkdir(parents=True, exist_ok=True)
    misplaced.write_text(
        (root / "generated" / "orders.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "generated" / "test_orders.py").write_text(
        (root / "tests" / "test_orders.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    promote_kpi_artifacts(root)
    assert (root / "generated" / "orders.py").is_file()
    assert (root / "tests" / "test_orders.py").is_file()
    assert not misplaced.exists()
    assert not (root / "generated" / "test_orders.py").exists()

    escaped = tool.execute(
        {
            "workflow_id": "wf-kpi",
            "filename": "../generated/orders.py",
            "code": "x = 1\n",
        }
    )
    assert escaped.ok is False

    runner = CodeRunPythonTool(AgentWorkspaceResolver(tmp_path))
    ran = runner.execute(
        {"workflow_id": "wf-kpi", "filename": "tests/test_orders.py", "timeout_seconds": 30}
    )
    assert ran.ok is True
    assert ran.output_data.get("exit_code") == 0

    broken = tool.execute(
        {
            "workflow_id": "wf-kpi",
            "filename": "tests/test_orders.py",
            "code": "def test_orders():\n    assert 1 == 0\n",
        }
    )
    assert broken.ok is True
    failed = runner.execute(
        {"workflow_id": "wf-kpi", "filename": "tests/test_orders.py", "timeout_seconds": 30}
    )
    assert failed.ok is False
    assert "1 failed" in str(failed.error_message or "")
    assert "assert 1 == 0" in str(failed.error_message or "")
