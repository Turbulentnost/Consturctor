from __future__ import annotations

import os
import shutil
import stat
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.db.base import Base
from app.models import explorer as _models
from app.models import user as _user  # noqa: F401
from app.services import explorer, explorer_history

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="git не установлен")

OWNER = explorer.Actor(user_id="u1", fio="Мангасарян Давид Арменович", department="ИТ")
COLLEAGUE = explorer.Actor(user_id="u2", fio="Иванов Иван Иванович", department="ИТ")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "explorer_root", tmp_path / "Orchestrator")
    engine = create_engine("sqlite://", future=True)
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


def _repo():
    return settings.explorer_root / "мангасарян" / explorer_history.REPO_DIR


def _git(*args: str) -> str:
    out = subprocess.run(
        [GIT, "-c", "safe.directory=*", "-c", "core.quotepath=off", f"--git-dir={_repo()}", *args],
        capture_output=True,
        check=True,
    )
    return out.stdout.decode("utf-8").strip()


def _files(branch: str) -> list[str]:
    return sorted(filter(None, _git("ls-tree", "-r", "--name-only", branch).splitlines()))


def _content(db, branch: str, path: str) -> bytes:
    key = db.get(_models.ExplorerHistoryRepo, "мангасарян").key
    return explorer_history.read_blob(GIT, _repo(), key, branch, path)


def test_first_file_creates_repo_and_owner_branch(db):
    explorer.create_file(db, OWNER, None, "план.txt", b"secret plan", explorer.AccessSpec())
    explorer_history.drain()
    assert (_repo() / "HEAD").exists()
    assert _git("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines() == ["main", "user-u1"]
    assert _files("main") == []
    assert _files("user-u1") == ["план.txt"]
    assert _content(db, "user-u1", "план.txt") == b"secret plan"
    raw = subprocess.run(
        [GIT, "-c", "safe.directory=*", f"--git-dir={_repo()}", "cat-file", "blob", "user-u1:план.txt"],
        capture_output=True,
        check=True,
    ).stdout
    assert b"secret plan" not in raw
    assert "Мангасарян Давид Арменович" in _git("log", "-1", "--format=%an", "user-u1")


def test_each_editor_gets_own_branch(db):
    item = explorer.create_file(
        db,
        OWNER,
        None,
        "общий.txt",
        b"v1",
        explorer.parse_access({"mode": "users", "users": [{"id": "u2", "fio": COLLEAGUE.fio, "permission": "write"}]}),
    )
    explorer.write_file(db, COLLEAGUE, item["id"], b"v2 by colleague")
    explorer.write_file(db, OWNER, item["id"], b"v3 by owner")
    explorer_history.drain()
    assert _content(db, "user-u2", "общий.txt") == b"v2 by colleague"
    assert _content(db, "user-u1", "общий.txt") == b"v3 by owner"
    assert _git("log", "--format=%s", "user-u1").splitlines() == [
        "Изменил «общий.txt»",
        "Создал «общий.txt»",
        "Создана история папки",
    ]
    assert "Иванов Иван Иванович" in _git("log", "-1", "--format=%an", "user-u2")


def test_delete_is_recorded(db):
    folder = explorer.create_folder(db, OWNER, None, "Проекты [2026]")
    explorer.create_file(db, OWNER, folder["id"], "a.txt", b"a", explorer.AccessSpec())
    item = explorer.create_file(db, OWNER, None, "b.txt", b"b", explorer.AccessSpec())
    explorer.delete_entry(db, OWNER, item["id"])
    explorer_history.drain()
    assert _files("user-u1") == ["Проекты [2026]/a.txt"]
    explorer.delete_entry(db, OWNER, folder["id"])
    explorer_history.drain()
    assert _files("user-u1") == []
    assert _content(db, "user-u1~1", "Проекты [2026]/a.txt") == b"a"


def test_existing_files_go_to_main_snapshot(db):
    explorer.create_file(db, OWNER, None, "старый.txt", b"old", explorer.AccessSpec())
    explorer_history.drain()
    shutil.rmtree(_repo(), onexc=lambda fn, path, _exc: (os.chmod(path, stat.S_IWRITE), fn(path)))
    db.delete(db.get(_models.ExplorerHistoryRepo, "мангасарян"))
    db.commit()
    explorer.create_file(db, OWNER, None, "второй.txt", b"2", explorer.AccessSpec())
    explorer_history.drain()
    assert _files("main") == ["старый.txt"]
    assert _content(db, "main", "старый.txt") == b"old"
    assert _files("user-u1") == ["второй.txt", "старый.txt"]


def test_repo_folder_name_is_reserved(db):
    with pytest.raises(explorer.ExplorerError):
        explorer.create_folder(db, OWNER, None, explorer_history.REPO_DIR)
