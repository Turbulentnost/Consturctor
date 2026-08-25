from datetime import date, datetime, timezone

from app.api_client import WorkflowFileItem, WorkflowFiles, WorkflowListItem
from app.ui.pages.platform_files_page import (
    PlatformFileRow,
    collect_weeks,
    current_week_monday,
    file_week_monday,
    filter_week_files,
    group_file_sessions,
    parse_file_dt,
    rows_from_workflow_files,
    week_monday,
    week_range_text,
    week_title,
)


def test_week_helpers_group_today_yesterday_and_older() -> None:
    today = date(2026, 8, 25)
    monday = current_week_monday(today)
    assert monday == date(2026, 8, 24)
    assert week_title(monday, today=today) == "Эта неделя"
    assert week_title(date(2026, 8, 17), today=today) == "Прошлая неделя"
    assert week_range_text(date(2026, 8, 10)) == "10 авг - 16 авг 2026"
    parsed = parse_file_dt("2026-08-12T10:00:00+00:00")
    assert parsed == datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    assert file_week_monday("", fallback=monday) == monday
    assert week_monday(parsed) == date(2026, 8, 10)


def test_filter_week_files_keeps_current_week_and_agent_search() -> None:
    today = date(2026, 8, 25)
    monday = current_week_monday(today)
    rows = [
        PlatformFileRow(
            workflow_id="wf-1",
            agent_title="Контроль сроков",
            file_id="f-1",
            filename="plan.xlsx",
            created_at="2026-08-25T09:00:00+00:00",
        ),
        PlatformFileRow(
            workflow_id="wf-2",
            agent_title="Отчётность",
            file_id="f-2",
            filename="old.docx",
            created_at="2026-08-10T09:00:00+00:00",
        ),
        PlatformFileRow(
            workflow_id="wf-3",
            agent_title="Контроль сроков",
            file_id="f-3",
            filename="notes.txt",
            created_at="",
        ),
    ]
    weeks = collect_weeks(rows, today=today)
    assert weeks[0] == date(2026, 8, 10)
    assert weeks[-1] == monday
    current = filter_week_files(rows, monday, today=today)
    assert [item.file_id for item in current] == ["f-1", "f-3"]
    found = filter_week_files(rows, monday, "контроль", today=today)
    assert [item.file_id for item in found] == ["f-1", "f-3"]
    none = filter_week_files(rows, monday, "old", today=today)
    assert none == []


def test_rows_from_workflow_files_keep_agent_and_ids() -> None:
    workflow = WorkflowListItem(id="wf-9", title="ИИ-агент KPI", phase="done")
    files = WorkflowFiles(
        user_files=[
            WorkflowFileItem(
                id="u-1",
                workflow_id="wf-9",
                filename="reglament.docx",
                source="user",
                size=1200,
                created_at="2026-08-25T11:00:00+00:00",
            )
        ],
        agent_files=[
            WorkflowFileItem(
                id="a-1",
                workflow_id="wf-9",
                filename="result.xlsx",
                source="agent",
                size=4096,
                created_at="2026-08-25T12:00:00+00:00",
                run_id="run-22",
                origin="sdk_output",
            )
        ],
    )
    rows = rows_from_workflow_files(workflow, files)
    assert [item.filename for item in rows] == ["reglament.docx", "result.xlsx"]
    assert all(item.agent_title == "ИИ-агент KPI" for item in rows)
    assert all(item.workflow_id == "wf-9" for item in rows)
    assert rows[1].source == "agent"
    assert rows[1].run_id == "run-22"


def test_group_file_sessions_splits_formation_and_runs() -> None:
    rows = [
        PlatformFileRow(
            workflow_id="wf-1",
            agent_title="Контроль сроков",
            file_id="u-1",
            filename="notes.txt",
            source="user",
            created_at="2026-08-25T09:00:00+00:00",
        ),
        PlatformFileRow(
            workflow_id="wf-1",
            agent_title="Контроль сроков",
            file_id="a-1",
            filename="Результат.md",
            source="agent",
            created_at="2026-08-25T12:00:00+00:00",
            run_id="run-1",
        ),
        PlatformFileRow(
            workflow_id="wf-1",
            agent_title="Контроль сроков",
            file_id="a-2",
            filename="AGENTS.md",
            source="agent",
            created_at="2026-08-25T12:05:00+00:00",
            run_id="run-1",
        ),
        PlatformFileRow(
            workflow_id="wf-1",
            agent_title="Контроль сроков",
            file_id="a-3",
            filename="later.md",
            source="agent",
            created_at="2026-08-25T15:00:00+00:00",
            run_id="run-2",
        ),
    ]
    groups = group_file_sessions(rows)
    assert [item.title for item in groups] == ["Формирование агента", "Запуск агента", "Запуск агента"]
    assert [item.file_id for item in groups[0].ours] == ["u-1"]
    assert groups[0].agent == ()
    assert groups[1].run_id == "run-2"
    assert [item.file_id for item in groups[1].agent] == ["a-3"]
    assert groups[2].run_id == "run-1"
    assert [item.file_id for item in groups[2].agent] == ["a-1", "a-2"]
    assert groups[2].ours == ()
