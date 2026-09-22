from pathlib import Path

from app.tools.ac.workers.mail_incoming_onec import stage_incoming_msg_file
from app.tools.ac.workers.onec_com_actions import _bsl_escape


def test_bsl_escape_windows_path(tmp_path: Path, monkeypatch) -> None:
    msg = tmp_path / "letter.msg"
    msg.write_bytes(b"x")
    escaped = _bsl_escape(str(msg))
    assert "\\\\" in escaped or "/" in escaped
    assert '"' not in escaped.replace('""', "")


def test_stage_incoming_msg_file(tmp_path: Path, monkeypatch) -> None:
    src = tmp_path / "src.msg"
    src.write_bytes(b"outlook-bytes")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    staged = stage_incoming_msg_file(str(src), entry_id="entry-abc", file_name="test.msg")
    assert staged.is_file()
    assert staged.read_bytes() == b"outlook-bytes"
