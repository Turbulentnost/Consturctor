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


@pytest.fixture(autouse=True)
def _isolated_transcripts(tmp_path, monkeypatch):
    import app.services.audio_transcribe as audio_mod

    monkeypatch.setattr(audio_mod, "_transcript_dir", lambda: tmp_path)
    monkeypatch.setattr(audio_mod, "_decode", lambda path: [0.0] * (9 * audio_mod._SAMPLE_RATE))
    monkeypatch.delenv("WHISPER_BEAM_SIZE", raising=False)
    audio_mod._cache.clear()
    yield
    audio_mod._cache.clear()


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

    import app.services.audio_transcribe as audio_mod

    audio_mod._cache.clear()
    result = transcribe_run_attachment(file_id="file-1", user_id="user-1")

    assert result["filename"] == "meeting.m4a"
    assert result["duration_sec"] == 9.0
    assert result["segment_count"] == 2
    assert result["cached"] is False
    assert "Добрый день" in result["preview"]
    text = open(result["transcript_path"], encoding="utf-8").read()
    assert "[00:00–00:03] Добрый день, коллеги." in text
    assert "[00:03–00:07] Начинаем совещание." in text
    assert "segments" not in result
    assert result["diarization"] == "none"

    calls = {"n": 0}
    real = audio_mod._get_model

    def counting():
        calls["n"] += 1
        return real()

    monkeypatch.setattr(audio_mod, "_get_model", counting)
    again = transcribe_run_attachment(file_id="file-1", user_id="user-1")
    assert again["cached"] is True
    assert again["transcript_path"] == result["transcript_path"]
    assert calls["n"] == 0


def test_long_audio_is_transcribed_in_chunks_with_shifted_timecodes(monkeypatch) -> None:
    import app.services.audio_transcribe as audio_mod

    Session = _session_factory()
    _seed_audio_file(Session)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    monkeypatch.setattr(audio_mod, "_CHUNK_SECONDS", 4)
    lengths: list[int] = []

    class _ChunkModel:
        def transcribe(self, audio, **kwargs):
            lengths.append(len(audio))
            return iter([SimpleNamespace(start=1.0, end=2.0, text=" фраза")]), SimpleNamespace(duration=4.0)

    monkeypatch.setattr(audio_mod, "_get_model", lambda: _ChunkModel())
    result = transcribe_run_attachment(file_id="file-1", user_id="user-1")

    rate = audio_mod._SAMPLE_RATE
    assert lengths == [4 * rate, 4 * rate, 1 * rate]
    assert result["duration_sec"] == 9.0 and result["segment_count"] == 3
    text = open(result["transcript_path"], encoding="utf-8").read()
    assert "[00:01–00:02] фраза" in text
    assert "[00:05–00:06] фраза" in text
    assert "[00:09–00:10] фраза" in text


def test_missing_faster_whisper_is_installed_once(monkeypatch) -> None:
    import builtins

    import app.services.audio_transcribe as audio_mod

    real_import = builtins.__import__
    state = {"installed": False, "installs": 0}

    def fake_import(name, *args, **kwargs):
        if name == "faster_whisper" and not state["installed"]:
            raise ImportError("No module named 'faster_whisper'")
        if name == "faster_whisper":
            return SimpleNamespace(WhisperModel=lambda *a, **k: "model")
        return real_import(name, *args, **kwargs)

    def fake_install():
        state["installs"] += 1
        state["installed"] = True

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(audio_mod, "_install_faster_whisper", fake_install)
    monkeypatch.setattr(audio_mod, "_model", None)

    assert audio_mod._get_model() == "model"
    assert state["installs"] == 1


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


def test_transcribe_uses_fast_decoding(monkeypatch) -> None:
    Session = _session_factory()
    _seed_audio_file(Session)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    seen: dict = {}

    class _RecordingModel(_FakeModel):
        def transcribe(self, path, **kwargs):
            seen.update(kwargs)
            return super().transcribe(path, **kwargs)

    monkeypatch.setattr("app.services.audio_transcribe._get_model", lambda: _RecordingModel())
    transcribe_run_attachment(file_id="file-1", user_id="user-1")
    assert seen["beam_size"] == 1
    assert seen["condition_on_previous_text"] is False
    assert seen["vad_filter"] is True

    import app.services.audio_transcribe as audio_mod

    audio_mod._cache.clear()
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "5")
    transcribe_run_attachment(file_id="file-1", user_id="user-1")
    assert seen["beam_size"] == 5


def test_transcribe_disk_cache_survives_restart(monkeypatch) -> None:
    Session = _session_factory()
    _seed_audio_file(Session)
    monkeypatch.setattr(db_session, "SessionLocal", Session)
    monkeypatch.setattr("app.services.audio_transcribe._get_model", lambda: _FakeModel())

    import app.services.audio_transcribe as audio_mod

    first = transcribe_run_attachment(file_id="file-1", user_id="user-1")
    assert first["cached"] is False

    audio_mod._cache.clear()
    monkeypatch.setattr(
        audio_mod, "_get_model", lambda: pytest.fail("после перезапуска модель не должна грузиться")
    )
    again = transcribe_run_attachment(file_id="file-1", user_id="user-1")
    assert again["cached"] is True
    assert again["transcript_path"] == first["transcript_path"]
    assert again["segment_count"] == 2


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
