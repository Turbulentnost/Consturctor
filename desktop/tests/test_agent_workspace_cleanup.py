from __future__ import annotations

import tempfile
from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspace, AgentWorkspaceResolver, OUTPUT_SUBDIR


def test_resolve_output_stays_in_workspace(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    ws = AgentWorkspace(root, "agent-1")
    out_file = ws.resolve_output("report.xlsx")
    assert out_file.parent.name == OUTPUT_SUBDIR
    assert ws.is_path_allowed(out_file)


def test_cleanup_scratch_keeps_out_dir(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    ws = AgentWorkspace(root, "agent-2")
    scratch = ws.directory / "temp.xlsx"
    scratch.write_bytes(b"x")
    code_dir = ws.directory / "code"
    code_dir.mkdir()
    (code_dir / "run.py").write_text("print(1)", encoding="utf-8")
    deliverable = ws.resolve_output("result.xlsx")
    deliverable.write_bytes(b"data")

    removed = ws.cleanup_scratch()
    assert str(scratch) in removed or scratch.name in {Path(p).name for p in removed}
    assert deliverable.is_file()
    assert not code_dir.exists()


def test_sweep_stale_removes_old_dirs(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    old = AgentWorkspace(tmp_path, "old-agent")
    (old.directory / "note.txt").write_text("x", encoding="utf-8")
    import os
    import time

    stale_time = time.time() - 86400 * 30
    os.utime(old.directory, (stale_time, stale_time))

    fresh = AgentWorkspace(tmp_path, "fresh-agent")
    (fresh.directory / "note.txt").write_text("y", encoding="utf-8")

    removed = resolver.sweep_stale(max_age_days=7)
    assert any("old-agent" in item for item in removed)
    assert fresh.directory.is_dir()
