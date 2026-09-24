"""Agent library adopt: one clone for adopter, source owner untouched."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.agent_library import adopt_library_agent, list_agent_library


def _session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def _count_workflows(db: Session, user_id: str) -> int:
    return int(
        db.query(func.count())
        .select_from(Workflow)
        .filter(Workflow.user_id == user_id)
        .scalar()
        or 0
    )


def test_adopt_creates_one_clone_without_touching_source_owner() -> None:
    db = _session()
    owner_a = "user-a"
    owner_b = "user-b"
    source_id = "wf-source"
    now = datetime.now(timezone.utc)

    db.add(AppUser(id=owner_a, fio="Автор А"))
    db.add(AppUser(id=owner_b, fio="Подписчик Б"))
    source_local = {
        "published": True,
        "status": "published",
        "purpose": "functional",
        "tools": ["mail.send"],
        "trigger_summary": "по запросу",
    }
    db.add(
        Workflow(
            id=source_id,
            user_id=owner_a,
            title="Формирование протокола по аудиозаписи совещания",
            phase="done",
            plan_json={"goal": "Собрать протокол"},
            local_run=deepcopy(source_local),
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()

    source_before = db.get(Workflow, source_id)
    assert source_before is not None
    local_before = deepcopy(source_before.local_run or {})
    phase_before = source_before.phase
    title_before = source_before.title
    updated_before = source_before.updated_at
    count_a_before = _count_workflows(db, owner_a)
    count_b_before = _count_workflows(db, owner_b)

    result = adopt_library_agent(db, user_id=owner_b, source_workflow_id=source_id)

    assert result["ok"] is True
    clone_id = result["workflow_id"]
    assert clone_id and clone_id != source_id

    assert _count_workflows(db, owner_b) == count_b_before + 1
    assert _count_workflows(db, owner_a) == count_a_before

    source_after = db.get(Workflow, source_id)
    assert source_after is not None
    assert source_after.user_id == owner_a
    assert source_after.phase == phase_before
    assert source_after.title == title_before
    assert source_after.local_run == local_before
    assert source_after.updated_at == updated_before

    clone = db.get(Workflow, clone_id)
    assert clone is not None
    assert clone.user_id == owner_b
    assert clone.phase == "done"
    assert (clone.local_run or {}).get("library_source_id") == source_id

    # Second adopt is idempotent — still one clone for B, nothing new for A.
    again = adopt_library_agent(db, user_id=owner_b, source_workflow_id=source_id)
    assert again["workflow_id"] == clone_id
    assert _count_workflows(db, owner_b) == count_b_before + 1
    assert _count_workflows(db, owner_a) == count_a_before

    lib_a = list_agent_library(db, user_id=owner_a)
    lib_b = list_agent_library(db, user_id=owner_b)

    # Clone must not reappear in the shared catalog (incl. for the source author).
    assert all(item["workflow_id"] != clone_id for item in lib_a["catalog"])
    assert all(item["workflow_id"] != clone_id for item in lib_b["catalog"])

    # Source stays in author's «Мои агенты» once; adopter sees exactly one card.
    a_mine = [item for item in lib_a["adopted"] if item["workflow_id"] == source_id]
    assert len(a_mine) == 1
    b_mine = [
        item
        for item in lib_b["adopted"]
        if item["workflow_id"] == clone_id or item.get("adopted_workflow_id") == clone_id
    ]
    assert len(b_mine) == 1
