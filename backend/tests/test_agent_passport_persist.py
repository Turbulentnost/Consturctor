"""Passport draft persistence and visible LLM errors."""

from __future__ import annotations

from app.services.agent_passport import persist
from app.services.agent_passport.service import AgentPassport, draft_passport
from app.services.agent_passport.types import ExtractedFunction


def test_write_and_read_saved_passport() -> None:
    passport = AgentPassport(name="Контроль", goal="не срывать сроки", source="llm")
    payload = persist.session_payload(
        passport,
        excerpt="мониторинг сроков",
        functions=[ExtractedFunction(name="Читать статусы")],
        bp_name="Контроль",
        qa_history=[{"prompt": "Когда запускать?", "answer": "по событию", "files": []}],
    )
    stored = persist.write_saved({}, "fn-1", payload)
    loaded = persist.read_saved(stored, "fn-1")
    assert loaded is not None
    restored = persist.passport_from_payload(loaded)
    assert restored is not None
    assert restored.name == "Контроль"
    assert restored.goal == "не срывать сроки"
    assert loaded["qa_history"][0]["answer"] == "по событию"
    assert persist.read_saved(stored, "other") is None


def test_draft_passport_keeps_cursor_error(monkeypatch) -> None:
    from app.services.agent_passport import cursor_agent as cursor_service

    def _fail(*_args, **_kwargs):
        return None, ""

    monkeypatch.setattr(cursor_service, "generate", _fail)
    monkeypatch.setattr(cursor_service, "last_error", lambda: "Cursor API HTTP 401: invalid key")
    passport = draft_passport(
        bp_name="Контроль дебиторки",
        excerpt="поступила новая заявка на отгрузку",
        functions=[ExtractedFunction(name="Проверить задолженность")],
    )
    assert passport.source == "heuristic"
    assert "401" in passport.llm_error
    assert passport.name


def test_draft_passport_uses_cursor(monkeypatch) -> None:
    from app.services.agent_passport import cursor_agent as cursor_service

    def _ok(*_args, **_kwargs):
        return (
            '{"name":"Контроль","goal":"не срывать","trigger":"заявка",'
            '"receives":"заказ","checks":"1С","decisions":"эскалация",'
            '"can_autonomous":"","needs_human_approval":"","forbidden":"",'
            '"result":"отчёт"}',
            "bc-agent-1",
        )

    monkeypatch.setattr(cursor_service, "generate", _ok)
    passport = draft_passport(
        bp_name="Контроль дебиторки",
        excerpt="поступила новая заявка на отгрузку",
        functions=[ExtractedFunction(name="Проверить задолженность")],
    )
    assert passport.source == "cursor"
    assert passport.cursor_agent_id == "bc-agent-1"
    assert passport.goal == "не срывать"
    assert not passport.llm_error


def test_store_key_prefers_function_id() -> None:
    assert persist.store_key("fn-9", "agent-1") == "fn-9"
    assert persist.store_key("", "agent-1") == "agent-1"
    assert persist.store_key("", "") == ""
