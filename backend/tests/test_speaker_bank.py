from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.meeting_audio import MeetingTranscript, VoiceProfile
from app.services import speaker_bank
from app.services.speaker_bank import best_voice_match, fio_initials, relabel_speaker, voice_labels


def _memory_db(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[MeetingTranscript.__table__, VoiceProfile.__table__])
    factory = sessionmaker(bind=engine, autoflush=False, future=True)
    monkeypatch.setattr("app.db.session.SessionLocal", factory)
    return factory


def _transcript(row_id: str, user_id: str, speakers: list[str], age_minutes: int) -> MeetingTranscript:
    return MeetingTranscript(
        id=row_id,
        user_id=user_id,
        filename="Meeting.wav",
        sha256="digest",
        duration_sec=60.0,
        transcript_path="C:/tmp/digest-Meeting.txt",
        full_text="",
        segments=[{"start": 0, "end": 1, "speaker": name, "text": "да"} for name in speakers],
        embeddings={},
        speaker_map={},
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )


def test_cached_transcript_is_claimed_by_caller(monkeypatch) -> None:
    factory = _memory_db(monkeypatch)
    with factory() as db:
        db.add(_transcript("clean", "ilchenko", ["Голос 1", "Голос 2 + Голос 1 (одновременно)"], 60))
        db.add(_transcript("bound", "ilchenko", ["Голос 1", "Донцова А.Е."], 10))
        db.commit()

    claimed = speaker_bank.claim_transcript("bound", "david", "digest")
    assert claimed is not None
    assert claimed["transcript_id"] not in {"clean", "bound"}
    assert claimed["pristine"] is True
    assert [row["speaker"] for row in claimed["segments"]] == ["Голос 1", "Голос 2 + Голос 1 (одновременно)"]
    with factory() as db:
        assert db.get(MeetingTranscript, claimed["transcript_id"]).user_id == "david"

    again = speaker_bank.claim_transcript("bound", "david", "digest")
    assert again is not None and again["transcript_id"] == claimed["transcript_id"]
    own = speaker_bank.claim_transcript("bound", "ilchenko", "digest")
    assert own is not None and own["transcript_id"] == "clean"


def test_bound_transcript_gets_its_own_file() -> None:
    path = speaker_bank._bound_path("C:/tmp/6b5294454209-Meeting.txt", "912f2119-ec9d")
    assert path.name == "6b5294454209-Meeting-912f2119.txt"
    assert speaker_bank._bound_path(str(path), "912f2119-ec9d") == path


def test_fio_initials() -> None:
    assert fio_initials("Амураль Игорь Борисович") == "Амураль И.Б."
    assert fio_initials("Донцова  анна") == "Донцова А."
    assert fio_initials("Ксения") == "Ксения"


def test_known_voice_needs_a_clear_winner() -> None:
    ivan = [1.0, 0.0, 0.0]
    petr = [0.0, 1.0, 0.0]
    profiles = [
        ("p1", "u1", "Иванов Иван", ivan),
        ("p2", "u2", "Петров Пётр", petr),
    ]
    match = best_voice_match([0.99, 0.01, 0.0], profiles)
    assert match is not None
    assert match["fio"] == "Иванов Иван"

    ambiguous = best_voice_match([0.7, 0.7, 0.0], profiles)
    assert ambiguous is None

    stranger = best_voice_match([0.0, 0.0, 1.0], profiles)
    assert stranger is None


def test_relabel_replaces_only_voice_marks() -> None:
    mapping = {"Голос 2": "Амураль Игорь Борисович"}
    text = "[00:01–00:04] Голос 2: план факта\n[00:05–00:08] Голос 1 + Голос 2 (одновременно): да"
    renamed = relabel_speaker(text, mapping)
    assert "Амураль Игорь Борисович" in renamed
    assert "Голос 1" in renamed
    assert "Голос 2" not in renamed.replace("Амураль Игорь Борисович", "")
    labels = voice_labels(
        [
            {"speaker": "Голос 1"},
            {"speaker": "Голос 1 + Голос 2 (одновременно)"},
        ]
    )
    assert labels == ["Голос 1", "Голос 2"]
