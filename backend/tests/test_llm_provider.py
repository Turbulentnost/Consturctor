from app.services.llm_provider import effective_llm_provider, llm_ready


def test_effective_llm_stub_by_default(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "llm_provider", "stub")
    monkeypatch.setattr(settings, "cursor_api_key", "")
    monkeypatch.setattr(settings, "claude_api_key", "")
    monkeypatch.setattr(settings, "chad_api_key", "")
    assert effective_llm_provider() == "stub"
    assert llm_ready() is False


def test_effective_llm_cursor(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "llm_provider", "cursor")
    monkeypatch.setattr(settings, "cursor_api_key", "crsr_test")
    assert effective_llm_provider() == "cursor"
    assert llm_ready() is True


def test_effective_llm_cursor_without_key(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "llm_provider", "cursor")
    monkeypatch.setattr(settings, "cursor_api_key", "")
    monkeypatch.setattr(settings, "claude_api_key", "")
    monkeypatch.setattr(settings, "chad_api_key", "")
    assert effective_llm_provider() == "stub"
