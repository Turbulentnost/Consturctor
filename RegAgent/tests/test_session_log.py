from pathlib import Path

from app.storage.session_log import (
    format_transcript,
    load_session_log,
    save_session_log,
    session_log_path,
)


def test_save_and_load_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.storage.session_log.WORKSPACES_DIR", tmp_path)
    workspace = tmp_path / "card-1"
    save_session_log(
        "card-1",
        [("user", "привет"), ("agent", "ответ")],
        workspace_dir=str(workspace),
    )
    loaded = load_session_log("card-1", str(workspace))
    assert loaded == [("user", "привет"), ("agent", "ответ")]
    assert session_log_path("card-1", str(workspace)).is_file()


def test_load_missing_is_empty(tmp_path: Path) -> None:
    assert load_session_log("missing", str(tmp_path / "nope")) == []


def test_format_transcript() -> None:
    text = format_transcript([("user", "задача"), ("error", "сбой")])
    assert "**Вы**" in text
    assert "задача" in text
    assert "**Ошибка**" in text
