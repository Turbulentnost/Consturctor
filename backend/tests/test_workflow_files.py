from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.workflow_files import (
    add_user_files_to_workflow,
    get_workflow_file,
    list_workflow_files,
    register_agent_files,
)
from app.services.workflows.service import create_workflow, get_workflow


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return Session()


def test_create_workflow_persists_files_as_bytea() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.commit()

    record = create_workflow(
        db,
        user_id="user-1",
        notes="",
        files=[("reglament.txt", "Правила отдела продаж".encode("utf-8"))],
    )

    row = db.query(Workflow).filter(Workflow.id == record.id).one()
    files = list_workflow_files(db, row=row)
    assert len(files.user_files) == 1
    item = get_workflow_file(db, row=row, file_id=files.user_files[0].id)
    assert item.content == "Правила отдела продаж".encode("utf-8")
    assert item.extracted_text == "Правила отдела продаж"
    assert item.summary
    hydrated = get_workflow(db, user_id="user-1", workflow_id=record.id)
    assert hydrated.attachments
    assert hydrated.attachments[0].stored_name == item.id


def test_register_agent_file_is_current_run_output() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    workflow = Workflow(id="wf-1", user_id="user-1", title="Агент", phase="tested")
    db.add(workflow)
    db.commit()

    register_agent_files(
        db,
        row=workflow,
        run_id="run-1",
        files=[("result.md", b"# result")],
    )
    db.commit()

    files = list_workflow_files(db, row=workflow, run_id="run-1")
    assert files.user_files == []
    assert len(files.agent_files) == 1
    assert files.agent_files[0].source == "agent"
    assert files.agent_files[0].scope == "run_output"
    assert files.agent_files[0].run_id == "run-1"


def test_add_user_file_refreshes_document_text_without_autoflush() -> None:
    db = _session()
    db.add(AppUser(id="user-1", fio="Тест"))
    workflow = Workflow(id="wf-1", user_id="user-1", title="Агент", phase="clarify")
    db.add(workflow)
    db.commit()

    add_user_files_to_workflow(
        db,
        row=workflow,
        files=[("extra.txt", b"important context")],
        origin="clarify_upload",
    )

    assert "important context" in workflow.document_text
    assert workflow.attachments_meta
