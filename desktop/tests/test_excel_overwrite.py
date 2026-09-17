from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspaceResolver
from app.tools.ac.excel_tools import (
    ExcelCreateWorkbookTool,
    ExcelEditWorkbookTool,
    ExcelReadWorkbookTool,
)


def test_create_workbook_overwrites_existing(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    tool = ExcelCreateWorkbookTool(resolver)
    args = {
        "workflow_id": "wf-excel",
        "filename": "plan.xlsx",
        "headers": ["a"],
        "rows": [[1]],
    }
    first = tool.execute(args)
    assert first.ok
    path = Path(first.output_data["path"])
    assert path.is_file()
    second = tool.execute({**args, "rows": [[2], [3]]})
    assert second.ok
    assert Path(second.output_data["path"]) == path
    assert second.output_data["written_rows"] == 3


def test_edit_workbook_rewrites_with_headers_rows(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    created = ExcelCreateWorkbookTool(resolver).execute(
        {"workflow_id": "wf-excel", "filename": "plan.xlsx", "headers": ["a"], "rows": [[1]]}
    )
    assert created.ok
    edited = ExcelEditWorkbookTool(resolver).execute(
        {
            "workflow_id": "wf-excel",
            "filename": "plan.xlsx",
            "headers": ["col"],
            "rows": [["x"]],
        }
    )
    assert edited.ok
    assert edited.output_data["filename"] == "plan.xlsx"


def test_ensure_xlsx_does_not_stack_text_suffix() -> None:
    from app.tools.ac.excel_tools import _ensure_xlsx

    assert _ensure_xlsx("report") == "report.xlsx"
    assert _ensure_xlsx("materials/plan.xlsx") == "materials/plan.xlsx"
    assert _ensure_xlsx("materials/001_notes.txt") == "materials/001_notes.xlsx"


def test_read_workbook_does_not_invent_txt_xlsx(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    workspace = resolver.for_agent("wf-excel")
    notes = workspace.directory / "materials" / "001_notes.txt"
    notes.parent.mkdir(parents=True)
    notes.write_text("регламент", encoding="utf-8")

    read = ExcelReadWorkbookTool(resolver).execute(
        {"workflow_id": "wf-excel", "filename": "materials/001_notes.txt"}
    )
    assert not read.ok
    assert read.error_type == "NOT_EXCEL"
    assert "materials/001_notes.txt" in read.error_message
    assert ".txt.xlsx" not in read.error_message


def test_read_workbook_finds_attachment_by_basename(tmp_path: Path) -> None:
    resolver = AgentWorkspaceResolver(tmp_path)
    created = ExcelCreateWorkbookTool(resolver).execute(
        {
            "workflow_id": "wf-excel",
            "filename": "report.xlsx",
            "headers": ["a"],
            "rows": [[1]],
        }
    )
    assert created.ok
    src = Path(created.output_data["path"])
    dest_dir = src.parent / "materials" / "attachments"
    dest_dir.mkdir(parents=True)
    dest = dest_dir / "002_report.xlsx"
    src.rename(dest)

    read = ExcelReadWorkbookTool(resolver).execute(
        {"workflow_id": "wf-excel", "filename": "report.xlsx"}
    )
    assert read.ok
    assert read.output_data["filename"] == "002_report.xlsx"
    assert read.output_data["row_count"] >= 1


def test_read_workbook_from_artifact_cache(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    resolver = AgentWorkspaceResolver(tmp_path)
    created = ExcelCreateWorkbookTool(resolver).execute(
        {
            "workflow_id": "wf-excel",
            "filename": "tracker.xlsx",
            "headers": ["a"],
            "rows": [[7]],
        }
    )
    assert created.ok
    from app.tools.ac.readable_files import artifact_cache_dir

    cache = artifact_cache_dir()
    cache.mkdir(parents=True)
    dest = cache / "tracker.xlsx"
    Path(created.output_data["path"]).replace(dest)

    read = ExcelReadWorkbookTool(resolver).execute(
        {"workflow_id": "wf-excel", "filename": str(dest)}
    )
    assert read.ok
    assert read.output_data["filename"] == "tracker.xlsx"
    flat = [cell for row in read.output_data["rows"] for cell in row]
    assert 7 in flat or "a" in flat
