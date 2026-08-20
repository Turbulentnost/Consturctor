from pathlib import Path

from app.tools.ac.agent_workspace import AgentWorkspaceResolver
from app.tools.ac.excel_tools import ExcelCreateWorkbookTool, ExcelEditWorkbookTool


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
