from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.base import Base
from app.models import explorer as explorer_models
from app.models.explorer_access import ExplorerAccessSuggestion
from app.models import user as user_models
from app.services import explorer
from app.services.server_agents.access_advisor import (
    DocumentView,
    GrantView,
    department_mentioned,
    grant_access,
    judge_suggestions,
    person_mentioned,
)
from app.services.server_agents.sources import extract_text

OWNER = explorer.Actor(user_id="u1", fio="Мангасарян Давид Арменович", department="ИТ")
COLLEAGUE = explorer.Actor(user_id="u2", fio="Иванов Иван Иванович", department="ИТ")
PERSON = {
    "user_id": "u2",
    "fio": "Соломичева Светлана Викторовна",
    "position": "специалист",
    "department": "Служба развития",
}
TEXT = "Прошу Соломичеву Светлану Викторовну согласовать график службы развития до пятницы."


def _person(fio: str):
    return PERSON if "соломич" in fio.lower() else None


def _department(name: str) -> str:
    return "Служба развития" if "развит" in name.lower() else ""


def _doc(**kwargs) -> DocumentView:
    base = dict(
        file_id="f1",
        name="записка.txt",
        owner_user_id="u1",
        owner_fio="Мангасарян Давид Арменович",
        mode="private",
        text=TEXT,
        updated_at=datetime.now(timezone.utc),
        grants=[],
    )
    base.update(kwargs)
    return DocumentView(**base)


def test_inflected_name_is_explicit():
    assert person_mentioned(PERSON["fio"], TEXT, "записка.txt")
    assert department_mentioned("Служба развития", TEXT, "записка.txt")
    assert not person_mentioned(PERSON["fio"], "Обновить регламент внедрения.", "регламент.txt")


def test_explicit_person_and_department_pass_and_guess_does_not():
    drafts = judge_suggestions(
        [_doc()],
        {
            "files": [
                {
                    "file_id": "f1",
                    "document_kind": "служебная записка",
                    "suggestions": [
                        {
                            "kind": "user",
                            "fio": "Соломичева Светлана",
                            "permission": "read",
                            "quote": "Прошу Соломичеву Светлану Викторовну согласовать",
                        },
                        {
                            "kind": "department",
                            "department": "служба развития",
                            "permission": "write",
                            "quote": "согласовать график службы развития до пятницы",
                        },
                    ],
                },
                {
                    "file_id": "f1",
                    "document_kind": "заметка",
                    "suggestions": [
                        {
                            "kind": "user",
                            "fio": "Соломичева Светлана",
                            "permission": "read",
                            "quote": "эта фраза в документе не встречается",
                        }
                    ],
                },
            ]
        },
        _person,
        _department,
    )
    assert [(item.kind, item.permission, item.grantee_label) for item in drafts] == [
        ("user", "read", PERSON["fio"]),
        ("department", "write", "Служба развития"),
    ]
    assert drafts[0].position == "специалист"


def test_existing_read_does_not_repeat_and_missing_write_stays():
    doc = _doc(
        grants=[GrantView("user", "u2", PERSON["fio"], "read")],
        mode="users",
    )
    drafts = judge_suggestions(
        [doc],
        {
            "files": [
                {
                    "file_id": "f1",
                    "document_kind": "служебная записка",
                    "suggestions": [
                        {
                            "kind": "user",
                            "fio": PERSON["fio"],
                            "permission": "read",
                            "quote": "Прошу Соломичеву Светлану Викторовну согласовать",
                        },
                        {
                            "kind": "user",
                            "fio": PERSON["fio"],
                            "permission": "write",
                            "quote": "Прошу Соломичеву Светлану Викторовну согласовать",
                        },
                    ],
                }
            ]
        },
        _person,
        _department,
    )
    assert [item.permission for item in drafts] == ["write"]


def test_open_for_everyone_needs_a_quote_from_the_file():
    drafts = judge_suggestions(
        [_doc(text="Объявление: в пятницу общий субботник во дворе, участие свободное.")],
        {
            "files": [
                {
                    "file_id": "f1",
                    "document_kind": "объявление",
                    "suggestions": [
                        {
                            "kind": "all",
                            "permission": "read",
                            "quote": "в пятницу общий субботник во дворе",
                            "why": "Это объявление о субботнике, персональных и коммерческих данных в тексте нет.",
                        }
                    ],
                }
            ]
        },
        _person,
        _department,
    )
    assert [item.kind for item in drafts] == ["all"]


def test_docx_text_is_extracted():
    xml = ElementTree.Element("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document")
    node = ElementTree.SubElement(xml, "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
    node.text = "Служба развития"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", ElementTree.tostring(xml, encoding="utf-8"))
    assert "Служба развития" in extract_text("положение.docx", buffer.getvalue())


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "explorer_root", tmp_path / "Orchestrator")
    engine = create_engine("sqlite://", future=True)

    @event.listens_for(engine, "connect")
    def _fk_on(conn, _record):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[
            explorer_models.ExplorerEntry.__table__,
            explorer_models.ExplorerFileKey.__table__,
            explorer_models.ExplorerKeyGrant.__table__,
            user_models.AppUser.__table__,
        ],
    )
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


def test_checkmark_gives_the_read_key(db):
    item = explorer.create_file(db, OWNER, None, "записка.txt", TEXT.encode(), explorer.AccessSpec())
    grant_access(
        db,
        ExplorerAccessSuggestion(
            id="s1",
            file_id=item["id"],
            file_name="записка.txt",
            owner_user_id=OWNER.user_id,
            document_kind="служебная записка",
            kind="user",
            grantee_id=COLLEAGUE.user_id,
            grantee_label=COLLEAGUE.fio,
            position="специалист",
            department="ИТ",
            permission="read",
            reason="",
            quote="",
            status="pending",
            run_id="",
        ),
    )
    db.commit()
    entry = db.get(explorer_models.ExplorerEntry, item["id"])
    assert explorer.access_level(db, COLLEAGUE, entry) == "read"
    with pytest.raises(explorer.ExplorerError):
        explorer.write_file(db, COLLEAGUE, item["id"], b"new")
