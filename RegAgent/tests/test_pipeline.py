from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from app.agent.dictionary import validate_dictionary
from app.agent.oneshot import run_oneshot_prompt
from app.agent.pipeline import CardPipelineService, PipelineError
from app.agent.prompts_create import (
    build_ui_spec_from_pipeline,
    filter_technical_clarify,
    parse_demo_result,
    validate_playbook_draft,
)
from app.agent.runtime import AgentRunCancelled, CardAgentSession
from app.models import (
    Card,
    ClarificationQuestion,
    DemoState,
    PassportData,
    PlaybookDraft,
    PlaybookStep,
)
from app.storage.repository import CardRepository
from app.tools.bridge import set_confirm_callback


@pytest.fixture()
def repo(tmp_path):
    db = tmp_path / "cards.db"
    return CardRepository(db)


@pytest.fixture()
def card(repo, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    c = Card(
        id="card-test",
        title="Тест",
        regulation_text="Регламент поручений документооборота",
        workspace_dir=str(ws),
        phase="demo",
    )
    c.passport = PassportData(
        title="Тест",
        goal="Поручения",
        system="onec",
        entity="porucheniya",
        operations=["docflow_tasks"],
        tools=["onec.docflow_tasks"],
    )
    c.playbook_draft = PlaybookDraft(
        status="verified",
        tools=["onec.docflow_tasks"],
        steps=[
            PlaybookStep(
                id="s1",
                title="Список поручений",
                action="Получить поручения",
                tool="onec.docflow_tasks",
                done_when="Список получен",
            )
        ],
    )
    repo.save(c)
    return c


def test_publish_without_verified_demo_fails(repo, card):
    card.demo = DemoState(ok=False)
    card.playbook_draft.status = "verified"
    repo.save(card)
    svc = CardPipelineService(repo)
    with pytest.raises(PipelineError, match="demo.ok"):
        svc.publish(card)


def test_publish_requires_verified_draft(repo, card):
    card.demo = DemoState(ok=True)
    card.playbook_draft.status = "draft"
    repo.save(card)
    with pytest.raises(PipelineError):
        CardPipelineService(repo).publish(card)


def test_publish_ok(repo, card):
    card.demo = DemoState(ok=True, verified=True)
    repo.save(card)
    published = CardPipelineService(repo).publish(card)
    assert published.phase == "published"
    assert published.ui_spec.actions
    assert published.playbook.steps


def test_autonomy_create_event_without_confirm_fails():
    import json

    from app.tools.bridge import _execute_tool

    set_confirm_callback(lambda _name, _args: False)
    raw = _execute_tool(
        {"tool": "outlook.create_event", "arguments": {"subject": "Test"}},
        MagicMock(),
    )
    payload = json.loads(raw)
    assert payload.get("ok") is False
    set_confirm_callback(None)


def test_docflow_not_routed_to_com_search():
    from app.tools.porucheniya_route import reroute_if_porucheniya

    name, _args = reroute_if_porucheniya(
        "onec.search_documents",
        {"query": "Документ.ТД_Поручения"},
    )
    assert name == "onec.docflow_tasks"


def test_resume_passes_custom_tools(card):
    session = CardAgentSession(card)
    opts = session._options()
    assert opts.local is not None
    assert "constructor_integrations" in (opts.local.custom_tools or {})


def test_technical_clarify_filtered():
    questions = [
        ClarificationQuestion(id="q1", question="Какой OData endpoint?", options=[]),
        ClarificationQuestion(id="q2", question="Кому слать отчёт?", options=["Мне", "Руководителю"]),
    ]
    kept = filter_technical_clarify(questions)
    assert len(kept) == 1
    assert kept[0].id == "q2"


def test_agent_prompt_disposed():
    with patch("cursor_sdk.Agent.prompt") as mock_prompt:
        mock_prompt.return_value = MagicMock(result='{"ok": true}')
        with patch("app.agent.oneshot.cursor_api_key", return_value="test-key"):
            with patch("app.agent.oneshot.cursor_model", return_value="composer-2.5"):
                run_oneshot_prompt("hello", cwd=".")
        mock_prompt.assert_called_once()


def test_create_send_always_wait(card):
    session = CardAgentSession(card)
    mock_agent = MagicMock()
    mock_run = MagicMock()
    mock_run.messages.return_value = []
    mock_run.wait.return_value = MagicMock(status="completed", result="ok")
    mock_agent.send.return_value = mock_run
    session._agent = mock_agent

    result = session.send("hi")
    assert result == "ok"
    mock_run.wait.assert_called_once()


def test_cancel_does_not_break_next_run(card):
    session = CardAgentSession(card)
    mock_agent = MagicMock()
    cancelled = threading.Event()

    def messages():
        cancelled.set()
        return []

    mock_run = MagicMock()
    mock_run.messages.side_effect = messages
    mock_run.wait.return_value = MagicMock(status="cancelled", result="")
    mock_agent.send.return_value = mock_run
    session._agent = mock_agent

    with pytest.raises(AgentRunCancelled):
        session.send("hi", cancel_check=cancelled.is_set)

    mock_run2 = MagicMock()
    mock_run2.messages.return_value = []
    mock_run2.wait.return_value = MagicMock(status="completed", result="done")
    mock_agent.send.return_value = mock_run2
    assert session.send("again") == "done"


def test_per_card_workspace_cwd(card, tmp_path):
    card.workspace_dir = str(tmp_path / "card-ws")
    session = CardAgentSession(card)
    opts = session._options()
    assert opts.local.cwd == card.workspace_dir


def test_dictionary_porucheniya_validation():
    result = validate_dictionary(
        system="onec",
        entity="porucheniya",
        tools=["onec.search_documents"],
    )
    assert result.ok is False
    assert any("docflow" in e for e in result.errors)


def test_build_ui_spec_from_pipeline(card):
    card.playbook = card.playbook_draft  # type: ignore[assignment]
    spec = build_ui_spec_from_pipeline(card)
    assert spec.title
    assert spec.actions


def test_parse_demo_result_ok():
    demo = parse_demo_result("RESULT:\nВсё выполнено успешно", steps_count=1)
    assert demo.ok is True


def test_playbook_draft_validation(card):
    draft = PlaybookDraft(
        status="draft",
        tools=["onec.docflow_tasks"],
        steps=[PlaybookStep(id="s1", title="T", action="A", tool="onec.docflow_tasks")],
    )
    verified = validate_playbook_draft(draft, card.passport)
    assert verified.status == "verified"
