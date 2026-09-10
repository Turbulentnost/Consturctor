from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models.regulation import RegulationDocument  # noqa: F401
from app.models.user import AppUser


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def test_parse_upload_job_does_not_need_request_session(tmp_path, monkeypatch) -> None:
    from app.api.v1 import regulations as api
    from app.config import settings

    Session = _session_factory()
    db = Session()
    db.add(AppUser(id="user-1", fio="Test"))
    db.commit()
    db.close()

    monkeypatch.setattr(api, "SessionLocal", Session)
    monkeypatch.setattr(settings, "regulation_storage_dir", tmp_path)
    monkeypatch.setattr(
        "app.services.regulation.pipeline._apply_cursor_entities",
        lambda result, user_id: result,
    )

    result = api._parse_upload_job(
        user_id="user-1",
        filename="note.txt",
        content_type="text/plain",
        data="Пункт регламента про совещания.".encode("utf-8"),
    )
    assert result.fileName == "note.txt"
    assert result.fragments
