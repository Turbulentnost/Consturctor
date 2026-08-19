"""SSE decoder must not replace Cyrillic split across byte chunks."""

from __future__ import annotations

from app.clients.cursor import _iter_sse_events


class _ChunkedResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    def iter_bytes(self, chunk_size: int = 256):
        del chunk_size
        yield from self._chunks


def test_sse_keeps_cyrillic_split_across_chunks() -> None:
    text = "качество непрерывный через"
    payload = (
        b'event: assistant\n'
        + f'data: {{"text": "{text}"}}\n\n'.encode("utf-8")
    )
    te_bytes = "т".encode("utf-8")
    split_at = payload.find(te_bytes) + 1
    assert 0 < split_at < len(payload)
    chunks = [payload[:split_at], payload[split_at:]]
    assert chunks[0][-1:] == te_bytes[:1]

    events = list(_iter_sse_events(_ChunkedResponse(chunks)))
    assert events
    event_name, data = events[0]
    assert event_name == "assistant"
    assert data["text"] == text
    assert "\ufffd" not in data["text"]


def test_sse_naive_decode_would_break_cyrillic() -> None:
    """Документирует старый баг: decode(errors=replace) на каждом чанке."""
    payload = 'data: {"text": "качество"}\n\n'.encode("utf-8")
    te_bytes = "т".encode("utf-8")
    split_at = payload.find(te_bytes) + 1
    first, second = payload[:split_at], payload[split_at:]
    broken = first.decode("utf-8", errors="replace") + second.decode(
        "utf-8", errors="replace"
    )
    assert "\ufffd" in broken


def test_create_run_when_ready_retries_409(monkeypatch) -> None:
    from app.clients import cursor as cursor_client
    from app.clients.cursor import CursorAgentError

    monkeypatch.setattr(cursor_client, "wait_until_run_idle", lambda *a, **k: {"status": "FINISHED"})
    monkeypatch.setattr(cursor_client.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def fake_create_run(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise CursorAgentError("занят", status_code=409)
        return {"id": "run-ok"}

    monkeypatch.setattr(cursor_client, "create_run", fake_create_run)
    data = cursor_client.create_run_when_ready(
        "agent-1",
        prompt="go",
        previous_run_id="run-old",
    )
    assert data["id"] == "run-ok"
    assert calls["n"] == 3
