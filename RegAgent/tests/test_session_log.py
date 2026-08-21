from pathlib import Path

from app.storage.session_log import (
    format_history_body,
    format_transcript,
    load_session_log,
    preview_text,
    save_session_log,
    session_log_path,
    should_collapse_entry,
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


def test_preview_text_compacts_and_truncates() -> None:
    assert preview_text("коротко") == "коротко"
    long = "слово " * 80
    preview = preview_text(long, limit=40)
    assert preview.endswith("…")
    assert len(preview) <= 42


def test_should_collapse_long_and_tool() -> None:
    assert should_collapse_entry("tool", "ok")
    assert should_collapse_entry("thinking", "план")
    assert not should_collapse_entry("user", "короткая задача")
    assert should_collapse_entry("agent", "x" * 300)


def test_format_history_body_pretty_json() -> None:
    pretty = format_history_body('✓ mcp\n{"status":"success","n":1}')
    assert pretty.startswith("✓ mcp")
    assert '"status": "success"' in pretty
