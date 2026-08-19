from __future__ import annotations

from app.models.workflow import Workflow
from app.services.agent_llm_reply import finalize_agent_answer


def test_finalize_agent_answer_without_llm(monkeypatch) -> None:
    monkeypatch.setattr("app.services.llm_provider.llm_ready", lambda: False)
    monkeypatch.setattr("app.services.llm_provider.effective_llm_provider", lambda: "stub")
    wf = Workflow(id="wf1", title="ACT agent")
    out = finalize_agent_answer(
        task="Выгрузи ACT",
        handler="act_porucheniya_registry",
        workflow=wf,
        factual_answer="88 документов.",
    )
    assert "88 документов" in out
    assert "LLM" in out


def test_finalize_agent_answer_uses_llm(monkeypatch) -> None:
    monkeypatch.setattr("app.services.llm_provider.llm_ready", lambda: True)
    monkeypatch.setattr("app.services.llm_provider.effective_llm_provider", lambda: "cursor")
    monkeypatch.setattr(
        "app.services.runtime_llm.generate",
        lambda *a, **k: "Я выгрузила 88 поручений ACT. Excel на рабочем столе.",
    )
    wf = Workflow(id="wf1", title="ACT agent")
    out = finalize_agent_answer(
        task="Выгрузи ACT",
        handler="act_porucheniya_registry",
        workflow=wf,
        factual_answer="технический отчёт",
    )
    assert "88 поручений" in out
