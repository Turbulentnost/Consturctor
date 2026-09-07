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


def test_resolve_finds_attachment_by_original_name(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    workspace = resolver.for_agent("wf-attach")
    folder = workspace.directory / "materials" / "attachments"
    folder.mkdir(parents=True)
    target = folder / "002_Отчет по количеству совещаний 2026 new.xlsx"
    target.write_bytes(b"x")

    found = workspace.resolve(
        "Отчет по количеству совещаний 2026 new.xlsx", must_exist=True
    )
    assert found == target.resolve()

    found_rel = workspace.resolve(
        "materials/attachments/002_Отчет по количеству совещаний 2026 new.xlsx",
        must_exist=True,
    )
    assert found_rel == target.resolve()


def test_resolve_create_keeps_requested_path(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    workspace = resolver.for_agent("wf-create")
    folder = workspace.directory / "materials" / "attachments"
    folder.mkdir(parents=True)
    (folder / "002_plan.xlsx").write_bytes(b"x")

    planned = workspace.resolve("plan.xlsx")
    assert planned == (workspace.directory / "plan.xlsx").resolve()
    assert planned != (folder / "002_plan.xlsx").resolve()
