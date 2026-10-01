import pytest

from app.services import audio_transcribe


def test_read_transcript_returns_text_from_transcript_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_transcribe, "_transcript_dir", lambda: tmp_path)
    path = tmp_path / "abc-meeting.txt"
    path.write_text("[00:01–00:05] Задача выполнена\n", encoding="utf-8")
    result = audio_transcribe.read_transcript(str(path))
    assert result["text"].startswith("[00:01–00:05]")


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
