from pathlib import Path

from app.tools.result_files import (
    clear_remembered_result_files,
    extract_result_files,
    is_document_path,
    remember_result_files,
    remembered_result_files,
    remembered_result_names,
)


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
