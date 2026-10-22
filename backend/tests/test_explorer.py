from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.base import Base
from app.models import explorer as _models  # noqa: F401
from app.models import user as _user  # noqa: F401
from app.services import explorer


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
            _models.ExplorerEntry.__table__,
            _models.ExplorerFileKey.__table__,
            _models.ExplorerKeyGrant.__table__,
            _models.ExplorerHistoryRepo.__table__,
            _user.AppUser.__table__,
        ],
    )
    session = sessionmaker(bind=engine, future=True)()
    yield session
    session.close()


OWNER = explorer.Actor(user_id="u1", fio="Мангасарян Давид Арменович", department="ИТ")
COLLEAGUE = explorer.Actor(user_id="u2", fio="Иванов Иван Иванович", department="ИТ")
STRANGER = explorer.Actor(user_id="u3", fio="Петров Пётр", department="Бухгалтерия")


def test_new_user_sees_only_shared_folder(db):
    listing = explorer.list_folder(db, OWNER, None)
    assert [item["id"] for item in listing["items"]] == [explorer.SHARED_FOLDER_ID]


def test_file_is_encrypted_in_user_folder(db):
    item = explorer.create_file(db, OWNER, None, "план.txt", b"secret plan", explorer.AccessSpec())
    on_disk = settings.explorer_root / "мангасарян" / "план.txt"
    assert on_disk.exists()
    raw = on_disk.read_bytes()
    assert raw.startswith(explorer.FILE_MAGIC)
    assert b"secret plan" not in raw
    _, data = explorer.read_file(db, OWNER, item["id"])
    assert data == b"secret plan"
    assert db.get(_models.ExplorerFileKey, item["id"]).owner_user_id == "u1"


def test_blank_docx_is_valid(db):
    item = explorer.create_file(db, OWNER, None, "отчёт.docx", None, explorer.AccessSpec())
    _, data = explorer.read_file(db, OWNER, item["id"])
    assert data[:2] == b"PK"


def test_nested_folder_and_up_navigation(db):
    folder = explorer.create_folder(db, OWNER, None, "Проекты")
    nested = explorer.create_folder(db, OWNER, folder["id"], "Вложенная")
    explorer.create_file(db, OWNER, folder["id"], "a.txt", b"x", explorer.AccessSpec())
    explorer.create_file(db, OWNER, nested["id"], "b.txt", b"abcd", explorer.AccessSpec())
    assert (settings.explorer_root / "мангасарян" / "Проекты" / "a.txt").exists()
    listing = explorer.list_folder(db, OWNER, folder["id"])
    assert listing["path"] == [{"id": folder["id"], "name": "Проекты"}]
    assert listing["parent_id"] is None
    assert [i["name"] for i in listing["items"]] == ["Вложенная", "a.txt"]
    assert next(i["size"] for i in listing["items"] if i["name"] == "Вложенная") == 4
    root = explorer.list_folder(db, OWNER, None)
    projects = next(item for item in root["items"] if item["name"] == "Проекты")
    assert projects["size"] == 5


def test_resolve_disk_path_uses_session_access(db):
    item = explorer.create_file(db, OWNER, None, "секрет.txt", b"hidden", explorer.AccessSpec())
    full = settings.explorer_root / "мангасарян" / "секрет.txt"
    assert explorer.resolve_disk_path(db, OWNER, str(full)) == {"id": item["id"], "name": "секрет.txt"}
    with pytest.raises(explorer.ExplorerError):
        explorer.resolve_disk_path(db, COLLEAGUE, str(full))
    shared = explorer.create_file(
        db,
        OWNER,
        None,
        "общий.txt",
        b"ok",
        explorer.parse_access({"mode": "users", "users": [{"id": "u2", "fio": "Иванов", "permission": "read"}]}),
    )
    shared_path = settings.explorer_root / "мангасарян" / "общий.txt"
    assert explorer.resolve_disk_path(db, COLLEAGUE, str(shared_path))["id"] == shared["id"]


def test_access_modes(db):
    private = explorer.create_file(db, OWNER, None, "p.txt", b"1", explorer.AccessSpec())
    dept = explorer.create_file(
        db, OWNER, None, "d.txt", b"2", explorer.parse_access({"mode": "department", "departments": ["ИТ"]})
    )
    person = explorer.create_file(
        db, OWNER, None, "u.txt", b"3", explorer.parse_access({"mode": "users", "users": [{"id": "u3", "fio": ""}]})
    )
    everyone = explorer.create_file(db, OWNER, None, "all.txt", b"4", explorer.parse_access({"mode": "all"}))

    def shared(actor):
        return {i["name"] for i in explorer.list_folder(db, actor, explorer.SHARED_FOLDER_ID)["items"]}

    assert shared(COLLEAGUE) == {"d.txt", "all.txt"}
    assert shared(STRANGER) == {"u.txt", "all.txt"}
    with pytest.raises(explorer.ExplorerError):
        explorer.read_file(db, COLLEAGUE, private["id"])
    assert explorer.read_file(db, STRANGER, person["id"])[1] == b"3"
    explorer.write_file(db, COLLEAGUE, dept["id"], b"edited")
    assert explorer.read_file(db, OWNER, dept["id"])[1] == b"edited"
    with pytest.raises(explorer.ExplorerError):
        explorer.delete_entry(db, COLLEAGUE, everyone["id"])


def test_tampered_file_is_rejected(db):
    item = explorer.create_file(db, OWNER, None, "t.txt", b"ok", explorer.AccessSpec())
    (settings.explorer_root / "мангасарян" / "t.txt").write_bytes(b"plain text dropped by hand")
    with pytest.raises(explorer.ExplorerError) as err:
        explorer.read_file(db, OWNER, item["id"])
    assert err.value.status_code == 409


def test_duplicate_name_and_bad_names(db):
    explorer.create_file(db, OWNER, None, "a.txt", b"", explorer.AccessSpec())
    with pytest.raises(explorer.ExplorerError):
        explorer.create_file(db, OWNER, None, "A.TXT", b"", explorer.AccessSpec())
    for bad in ("..", "a/b.txt", "con.txt", "noext"):
        with pytest.raises(explorer.ExplorerError):
            explorer.create_file(db, OWNER, None, bad, b"", explorer.AccessSpec())


def test_delete_folder_removes_tree(db):
    folder = explorer.create_folder(db, OWNER, None, "Старое")
    explorer.create_file(db, OWNER, folder["id"], "x.txt", b"x", explorer.AccessSpec())
    explorer.delete_entry(db, OWNER, folder["id"])
    assert not (settings.explorer_root / "мангасарян" / "Старое").exists()
    assert [i["id"] for i in explorer.list_folder(db, OWNER, None)["items"]] == [explorer.SHARED_FOLDER_ID]


def test_unreadable_owner_folder_uses_a_new_one(db, monkeypatch):
    explorer.create_file(db, OWNER, None, "a.txt", b"", explorer.AccessSpec())
    blocked = settings.explorer_root / "мангасарян"
    real_mkdir = Path.mkdir

    def guarded_mkdir(self, *args, **kwargs):
        if self == blocked:
            raise FileExistsError(183, "Невозможно создать файл, так как он уже существует")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", guarded_mkdir)
    explorer.create_file(db, OWNER, None, "b.txt", b"z", explorer.AccessSpec())
    assert (settings.explorer_root / "мангасарян_да" / "b.txt").exists()


def test_same_surname_gets_separate_folder(db):
    explorer.create_file(db, OWNER, None, "a.txt", b"", explorer.AccessSpec())
    namesake = explorer.Actor(user_id="u9", fio="Мангасарян Карен Ашотович", department="")
    explorer.create_file(db, namesake, None, "a.txt", b"", explorer.AccessSpec())
    assert (settings.explorer_root / "мангасарян_ка" / "a.txt").exists()


def test_create_file_issues_read_and_write_keys(db):
    item = explorer.create_file(
        db,
        OWNER,
        None,
        "k.txt",
        b"v1",
        explorer.parse_access(
            {
                "mode": "users",
                "users": [
                    {"id": "u2", "fio": "Иванов Иван Иванович", "permission": "read"},
                    {"id": "u4", "fio": "Сидоров", "permission": "write", "department": "ИТ"},
                ],
            }
        ),
    )
    key_row = db.get(explorer.ExplorerFileKey, item["id"])
    assert key_row is not None
    assert key_row.key and key_row.read_key
    assert key_row.key != key_row.read_key
    assert explorer.read_file(db, COLLEAGUE, item["id"])[1] == b"v1"
    with pytest.raises(explorer.ExplorerError):
        explorer.write_file(db, COLLEAGUE, item["id"], b"no")
    writer = explorer.Actor(user_id="u4", fio="Сидоров", department="ИТ")
    explorer.write_file(db, writer, item["id"], b"yes")
    assert explorer.read_file(db, OWNER, item["id"])[1] == b"yes"
