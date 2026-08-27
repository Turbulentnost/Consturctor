from pathlib import Path

from app.tools.result_files import (
    clear_remembered_result_files,
    extract_result_files,
    is_document_path,
    remember_result_files,
    remembered_result_files,
    remembered_result_names,
)


def test_as_document_accepts_path_under_workspaces_root(tmp_path: Path, monkeypatch) -> None:
    from app.tools.result_files import extract_result_files

    root = tmp_path / "agent_workspaces"
    other = root / "other-wf"
    other.mkdir(parents=True)
    report = other / "report.md"
    report.write_text("ok", encoding="utf-8")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path / "missing")
    monkeypatch.setattr("app.tools.ac.dispatch.workspaces_root", lambda: root)
    files = extract_result_files(
        {"file": str(report), "path": str(report)},
        tool="report.export_document",
        workflow_id="wf-1",
    )
    assert files == [report.resolve()]


def test_collect_output_files_from_dir_picks_root_markdown(tmp_path: Path) -> None:
    from app.tools.result_files import collect_output_files_from_dir

    (tmp_path / "materials").mkdir()
    (tmp_path / "materials" / "input.xlsx").write_bytes(b"xlsx")
    report = tmp_path / "plan.md"
    report.write_text("ok", encoding="utf-8")
    names = {path.name for path in collect_output_files_from_dir(tmp_path)}
    assert names == {"plan.md"}


def test_collect_workspace_outputs_skips_inputs(tmp_path: Path, monkeypatch) -> None:
    from app.tools.result_files import collect_workspace_output_files

    (tmp_path / "materials").mkdir()
    (tmp_path / "code").mkdir()
    (tmp_path / "tool_results").mkdir()
    (tmp_path / "materials" / "table.xlsx").write_bytes(b"xlsx")
    (tmp_path / "code" / "build.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "tool_results" / "dump.json").write_text("{}", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("brief", encoding="utf-8")
    report = tmp_path / "plan.md"
    report.write_text("ok", encoding="utf-8")
    events = tmp_path / "planned_events.json"
    events.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path)
    names = {path.name for path in collect_workspace_output_files("wf-1")}
    assert names == {"plan.md", "planned_events.json"}


def test_extract_run_python_collects_workspace_outputs(tmp_path: Path, monkeypatch) -> None:
    book = tmp_path / "slots.json"
    book.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path)
    files = extract_result_files(
        {"script": "code/build.py", "cwd": str(tmp_path)},
        tool="code.run_python",
        workflow_id="wf-1",
    )
    assert files == [book.resolve()]


def test_extract_skips_json_dump_and_read_tools(tmp_path: Path) -> None:
    book = tmp_path / "kalendar.xlsx"
    book.write_bytes(b"xlsx")
    assert extract_result_files({"path": str(book)}, tool="excel.list_files") == []
    assert extract_result_files({"path": str(book)}, tool="excel.read_workbook") == []
    assert extract_result_files({"path": str(book)}, tool="code.write_python") == []


def test_extract_excel_create_path(tmp_path: Path) -> None:
    book = tmp_path / "kalendar_serii.xlsx"
    book.write_bytes(b"xlsx")
    files = extract_result_files(
        {"filename": book.name, "path": str(book), "written_rows": 12},
        tool="excel.create_workbook",
    )
    assert files == [book.resolve()]
    assert is_document_path(files[0])


def test_extract_plan_export_file_key(tmp_path: Path) -> None:
    book = tmp_path / "report.xlsx"
    book.write_bytes(b"xlsx")
    files = extract_result_files({"file": str(book), "count": 3}, tool="plan_export")
    assert files == [book.resolve()]


def test_extract_ignores_relative_and_missing() -> None:
    assert extract_result_files({"path": "notes.xlsx"}, tool="excel.create_workbook") == []
    assert extract_result_files({"path": "C:/missing/nope.xlsx"}, tool="excel.create_workbook") == []
    assert extract_result_files({"filename": "a.xlsx"}, tool="excel.create_workbook") == []


def test_remembered_absolute_paths_survive_relative_files(tmp_path: Path) -> None:
    book = tmp_path / "plan-serii.xlsx"
    book.write_bytes(b"xlsx")
    clear_remembered_result_files("wf-1")
    remember_result_files([book], workflow_id="wf-1")
    relative = extract_result_files({"files": ["plan-serii.xlsx"]}, tool="excel.create_workbook")
    assert relative == []
    remembered = remembered_result_files("wf-1")
    assert remembered == [book.resolve()]
    assert "plan-serii.xlsx" in remembered_result_names("wf-1")
    clear_remembered_result_files("wf-1")


def test_extract_relative_name_via_workspace(tmp_path: Path, monkeypatch) -> None:
    book = tmp_path / "plan_serii_soveshchaniy.xlsx"
    book.write_bytes(b"xlsx")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path)
    files = extract_result_files(
        {"files": ["plan_serii_soveshchaniy.xlsx"]},
        tool="excel.create_workbook",
        workflow_id="wf-1",
    )
    assert files == [book.resolve()]


def test_publish_result_files_remembers_without_qt(tmp_path: Path, monkeypatch) -> None:
    from app.tools.result_files import publish_result_files

    book = tmp_path / "slots.json"
    book.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path)
    clear_remembered_result_files("wf-qt")

    class _NoApp:
        @staticmethod
        def instance():
            return None

    monkeypatch.setattr("PySide6.QtWidgets.QApplication", _NoApp)

    def _should_not_offer(*_args, **_kwargs):
        raise AssertionError("sidecar must not open Qt file cards")

    monkeypatch.setattr(
        "app.ui.widgets.result_file_card.offer_result_files",
        _should_not_offer,
    )
    publish_result_files({"ok": True}, tool="code.run_python", workflow_id="wf-qt")
    assert "slots.json" in remembered_result_names("wf-qt")
    clear_remembered_result_files("wf-qt")


def test_publish_answer_picks_excel_from_text(tmp_path: Path, monkeypatch) -> None:
    from app.tools.result_files import publish_answer_files

    book = tmp_path / "plan_serii_soveshchaniy.xlsx"
    book.write_bytes(b"xlsx")
    monkeypatch.setattr("app.tools.result_files.workspace_for", lambda _wid: tmp_path)
    offered: list[list] = []
    monkeypatch.setattr(
        "app.ui.widgets.result_file_card.offer_result_files",
        lambda files, workflow_id="": offered.append(list(files)),
    )
    publish_answer_files(
        workflow_id="wf-1",
        work={"text": "Файл `plan_serii_soveshchaniy.xlsx` уже есть."},
        text="Файл `plan_serii_soveshchaniy.xlsx` уже есть.",
    )
    names = {path.name for batch in offered for path in batch}
    assert "plan_serii_soveshchaniy.xlsx" in names
    assert "Результат.md" in names
