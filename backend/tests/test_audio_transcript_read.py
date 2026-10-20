import pytest

from app.services import audio_transcribe


def test_read_transcript_returns_text_from_transcript_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_transcribe, "_transcript_dir", lambda: tmp_path)
    path = tmp_path / "abc-meeting.txt"
    path.write_text("[00:01–00:05] Задача выполнена\n", encoding="utf-8")
    result = audio_transcribe.read_transcript(str(path))
    assert result["text"].startswith("[00:01–00:05]")


def _long_transcript(folder, count):
    lines = ["Файл: meeting.wav", "Длительность: 60:00", f"Сегментов: {count}", ""]
    lines += [f"[{i // 60:02d}:{i % 60:02d}–{i // 60:02d}:{i % 60:02d}] реплика {i}" for i in range(count)]
    path = folder / "abc-meeting.txt"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_read_transcript_parts_cover_every_line(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_transcribe, "_transcript_dir", lambda: tmp_path)
    path = _long_transcript(tmp_path, 250)
    first = audio_transcribe.read_transcript(str(path), 1)
    assert first["parts"] == 3
    assert first["next_part"] == 2
    seen = []
    for part in range(1, first["parts"] + 1):
        chunk = audio_transcribe.read_transcript(str(path), part)
        assert chunk["text"].startswith("Файл: meeting.wav")
        seen += [line for line in chunk["text"].splitlines() if line.startswith("[")]
    assert seen == [f"[{i // 60:02d}:{i % 60:02d}–{i // 60:02d}:{i % 60:02d}] реплика {i}" for i in range(250)]
    last = audio_transcribe.read_transcript(str(path), 3)
    assert last["next_part"] is None
    assert last["from"] == "04:00" and last["to"] == "04:09"


def test_read_transcript_rejects_missing_part(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_transcribe, "_transcript_dir", lambda: tmp_path)
    path = _long_transcript(tmp_path, 10)
    with pytest.raises(RuntimeError, match="Части 2 нет"):
        audio_transcribe.read_transcript(str(path), 2)


@pytest.mark.parametrize("name", ["../secret.txt", "cache.json"])
def test_read_transcript_rejects_other_files(tmp_path, monkeypatch, name):
    folder = tmp_path / "transcripts"
    folder.mkdir()
    monkeypatch.setattr(audio_transcribe, "_transcript_dir", lambda: folder)
    target = folder / name
    target.resolve().parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x", encoding="utf-8")
    with pytest.raises(RuntimeError, match="не файл расшифровки"):
        audio_transcribe.read_transcript(str(target))
