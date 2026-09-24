from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.session as db_session
from app.db.base import Base
from app.models.user import AppUser
from app.models.workflow import Workflow, WorkflowFile
from app.services.audio_transcribe import transcribe_run_attachment
from app.services.workflows.cursor_tools import (
    clear_tool_context,
    invoke_creation_tool,
    set_tool_context,
)


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _seed_audio_file(Session, *, filename: str = "meeting.m4a") -> None:
    db = Session()
    db.add(AppUser(id="user-1", fio="Тест"))
    db.add(AppUser(id="user-2", fio="Другой"))
    db.add(Workflow(id="wf-1", user_id="user-1", title="Протоколы", phase="tested"))
    db.commit()
    db.add(
        WorkflowFile(
            id="file-1",
            workflow_id="wf-1",
            run_id="run-1",
            source="user",
            scope="run_attachment",
            filename=filename,
            content=b"fake-audio-bytes",
        )
    )
    db.commit()
    db.close()


class _FakeModel:
    def transcribe(self, path, **kwargs):
        segments = [
            SimpleNamespace(start=0.0, end=3.5, text=" Добрый день, коллеги."),
            SimpleNamespace(start=3.5, end=7.2, text=" Начинаем совещание."),
            SimpleNamespace(start=7.2, end=9.0, text="   "),  # пустой — отбрасывается
        ]
        info = SimpleNamespace(duration=9.0)
        return iter(segments), info


def test_transcribe_run_attachment_returns_segments(monkeypatch) -> None:
    Session = _session_factory()
    _seed_audio_file(Session)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    monkeypatch.setattr(
        "app.services.audio_transcribe._get_model", lambda: _FakeModel()
    )

    result = transcribe_run_attachment(file_id="file-1", user_id="user-1")

    assert result["filename"] == "meeting.m4a"
    assert result["duration_sec"] == 9.0
    assert result["segments"] == [
        {"start": 0.0, "end": 3.5, "text": "Добрый день, коллеги."},
        {"start": 3.5, "end": 7.2, "text": "Начинаем совещание."},
    ]
    assert result["text"] == "Добрый день, коллеги.\nНачинаем совещание."
    assert result["diarization"] == "none"


def test_transcribe_passes_outlook_names_as_prompt(monkeypatch) -> None:
    Session = _session_factory()
    _seed_audio_file(Session)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    seen: dict = {}

    class _RecordingModel(_FakeModel):
        def transcribe(self, path, **kwargs):
            seen.update(kwargs)
            return super().transcribe(path, **kwargs)

    monkeypatch.setattr(
        "app.services.audio_transcribe._get_model", lambda: _RecordingModel()
    )
    import app.services.audio_transcribe as audio_mod

    audio_mod._cache.clear()

    result = transcribe_run_attachment(
        file_id="file-1",
        user_id="user-1",
        names=["Ильченко Екатерина Александровна", "Мегрелишвили Михаил Эмзарович"],
    )
    assert "Ильченко" in seen.get("initial_prompt", "")
    assert "Мегрелишвили" in result["names_hint"]


def test_transcribe_rejects_foreign_user(monkeypatch) -> None:
    Session = _session_factory()
    _seed_audio_file(Session)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    monkeypatch.setattr(
        "app.services.audio_transcribe._get_model",
        lambda: pytest.fail("модель не должна грузиться для чужого файла"),
    )

    with pytest.raises(RuntimeError, match="другого пользователя"):
        transcribe_run_attachment(file_id="file-1", user_id="user-2")


def test_transcribe_rejects_unsupported_extension(monkeypatch) -> None:
    Session = _session_factory()
    _seed_audio_file(Session, filename="notes.txt")
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    monkeypatch.setattr(
        "app.services.audio_transcribe._get_model",
        lambda: pytest.fail("модель не должна грузиться для txt"),
    )

    with pytest.raises(RuntimeError, match="Формат .txt не принимается"):
        transcribe_run_attachment(file_id="file-1", user_id="user-1")


def test_transcribe_missing_file(monkeypatch) -> None:
    Session = _session_factory()
    _seed_audio_file(Session)
    monkeypatch.setattr(db_session, "SessionLocal", Session)

    with pytest.raises(RuntimeError, match="не найден"):
        transcribe_run_attachment(file_id="no-such-file", user_id="user-1")


def test_invoke_creation_tool_routes_audio_transcribe(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_service(*, file_id: str, user_id: str, names=None, hint=""):
        calls.append({"file_id": file_id, "user_id": user_id, "names": names or []})
        return {"segments": [], "text": "", "duration_sec": 1.0, "filename": "a.mp3"}

    monkeypatch.setattr(
        "app.services.audio_transcribe.transcribe_run_attachment", fake_service
    )
    set_tool_context("run-1", "user-1")
    try:
        result = invoke_creation_tool(
            tool="audio.transcribe",
            arguments={"file_id": "file-9"},
            on_event=None,
        )
    finally:
        clear_tool_context()

    assert calls == [{"file_id": "file-9", "user_id": "user-1", "names": []}]
    assert result["filename"] == "a.mp3"


def test_invoke_creation_tool_transcribe_alias_and_fileId(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_service(*, file_id: str, user_id: str, names=None, hint=""):
        calls.append({"file_id": file_id, "user_id": user_id, "names": list(names or [])})
        return {"segments": [], "text": "", "duration_sec": 0.0, "filename": "b.wav"}

    monkeypatch.setattr(
        "app.services.audio_transcribe.transcribe_run_attachment", fake_service
    )
    set_tool_context("run-2", "user-7")
    try:
        invoke_creation_tool(
            tool="transcribe",
            arguments={"fileId": "file-42", "names": ["Ильченко Екатерина Александровна"]},
            on_event=None,
        )
    finally:
        clear_tool_context()

    assert calls == [
        {
            "file_id": "file-42",
            "user_id": "user-7",
            "names": ["Ильченко Екатерина Александровна"],
        }
    ]


def test_invoke_audio_transcribe_requires_file_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.audio_transcribe.transcribe_run_attachment",
        lambda **_kwargs: pytest.fail("сервис не должен вызываться без file_id"),
    )
    set_tool_context("run-3", "user-1")
    try:
        with pytest.raises(RuntimeError, match="file_id"):
            invoke_creation_tool(
                tool="audio.transcribe",
                arguments={},
                on_event=None,
            )
    finally:
        clear_tool_context()


def test_invoke_audio_transcribe_requires_session_user() -> None:
    clear_tool_context()
    with pytest.raises(RuntimeError, match="Нет пользователя"):
        invoke_creation_tool(
            tool="audio.transcribe",
            arguments={"file_id": "file-1"},
            on_event=None,
        )
