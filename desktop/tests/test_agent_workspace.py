from __future__ import annotations

from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspaceResolver


def test_list_files_includes_materials(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    workspace = resolver.for_agent("wf-test")
    (workspace.directory / "root.xlsx").write_bytes(b"x")
    materials = workspace.directory / "materials"
    materials.mkdir()
    (materials / "plan.xlsx").write_bytes(b"y")
    (workspace.directory / "code").mkdir()
    (workspace.directory / "code" / "main.py").write_text("print(1)\n", encoding="utf-8")

    names = {item["name"] for item in workspace.list_files()}
    assert "root.xlsx" in names
    assert "materials/plan.xlsx" in names
    assert "code/main.py" not in names
