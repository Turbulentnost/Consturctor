from app.api_client import WorkflowFileItem, WorkflowRecord
from app.ui.pages.workflow_page import (
    SUPPORTED_SUFFIXES,
    _file_meta_line,
    _format_file_size,
    when_to_run_known,
)
from app.ui.widgets.file_type_icon import elide_filename_middle, file_ext_label, file_type_style


def test_file_type_style_covers_supported_suffixes() -> None:
    for suffix in SUPPORTED_SUFFIXES:
        style = file_type_style(f"document{suffix}")
        assert style.ext
        assert style.color.startswith("#")
        assert style.soft.startswith("#")
        assert style.glyph


def test_file_type_style_known_office_and_fallback() -> None:
    word = file_type_style("Регламент отдела продаж.docx")
    assert word.ext == "DOCX"
    assert word.glyph == "W"
    excel = file_type_style("otchet.xlsx")
    assert excel.ext == "XLSX"
    assert excel.glyph == "X"
    pdf = file_type_style("map.pdf")
    assert pdf.kind == "pdf"
    unknown = file_type_style("notes.xyz")
    assert unknown.ext == "XYZ"
    assert unknown.glyph == "XY"
    assert file_ext_label("AGENTS.md") == "MD"


def test_file_meta_line_shows_size_and_origin() -> None:
    user = WorkflowFileItem(id="1", filename="notes.txt", size=5400, source="user")
    agent = WorkflowFileItem(id="2", filename="AGENTS.md", size=1024, source="agent")
    assert _file_meta_line(user) == f"{_format_file_size(5400)} • загружен вами"
    assert _file_meta_line(agent) == f"{_format_file_size(1024)} • создан агентом"
    assert _file_meta_line(None, pending=True) == "ожидает загрузки"


def test_elide_filename_keeps_extension_in_the_middle() -> None:
    long_name = "контроль_сроков_качества_рисков_проектов.docx"
    text = elide_filename_middle(long_name, max_chars=22)
    assert text.endswith(".docx")
    assert "..." in text
    assert text.startswith("контроль")
    assert elide_filename_middle("notes.txt", max_chars=22) == "notes.txt"


def test_when_to_run_known_from_draft_or_materials() -> None:
    empty = WorkflowRecord(id="wf-1", title="Агент", phase="designed")
    assert when_to_run_known(empty) is False
    draft = WorkflowRecord(
        id="wf-1",
        title="Агент",
        phase="designed",
        local_run={"playbook_draft": {"when_to_run": "ежедневно"}},
    )
    assert when_to_run_known(draft) is True
    notes = WorkflowRecord(
        id="wf-1",
        title="Агент",
        phase="designed",
        notes="Событийный триггер: событие вместо расписания",
    )
    assert when_to_run_known(notes) is True
