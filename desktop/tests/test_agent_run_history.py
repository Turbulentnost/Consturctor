from PySide6.QtWidgets import QApplication

from app.api_client import AgentRunHistoryItem
from app.ui.pages.agent_history_page import _events_for_run, _status_label
from app.ui.pages.agent_run_page import _event_card, _friendly_event, _work_result_event


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_friendly_event_maps_plan_think_tool_result() -> None:
    plan = _friendly_event({"type": "plan", "text": "s1 — Список"})
    assert plan == {"type": "plan", "title": "План", "text": "s1 — Список"}

    think = _friendly_event({"type": "thinking", "text": "сверяю штатку"})
    assert think["type"] == "thinking"

    decision = _friendly_event({"type": "decision", "text": "читаю подчинённых"})
    assert decision == {"type": "system", "text": "читаю подчинённых"}

    result = _friendly_event(
        {
            "type": "work_result",
            "text": "Сводка готова",
            "files": ["RESULT.md"],
        }
    )
    assert result["type"] == "work_result"
    assert "Сводка готова" in result["text"]
    assert "RESULT.md" in result["text"]


def test_work_result_is_separate_block() -> None:
    _ensure_app()
    event = _work_result_event({"files": ["a.xlsx"], "actions": ["открыть"]}, "Готово")
    assert event["type"] == "work_result"
    assert event["title"] == "Результат"
    card = _event_card(event, expanded=True)
    assert card._kind == "result"


def test_events_for_run_keeps_full_feed() -> None:
    item = AgentRunHistoryItem(
        id="r1",
        workflow_id="wf-1",
        message="запусти",
        status="ok",
        answer="Сводка",
        events=[
            {"type": "user_message", "text": "запусти"},
            {"type": "plan", "text": "s1 — Список"},
            {"type": "thinking", "text": "думаю"},
            {"type": "decision", "text": "вызываю users.subordinates"},
            {"type": "status", "text": "Агент работает…"},
            {
                "type": "tool_result",
                "tool": "users.subordinates",
                "result": {"users": [{"fio": "Иванов"}], "count": 1},
                "text": "users.subordinates\nготово",
            },
            {"type": "work_result", "text": "Сводка", "files": ["RESULT.md"]},
        ],
    )
    kinds = [event["type"] for event in _events_for_run(item)]
    assert "status" not in kinds
    assert kinds == [
        "user_message",
        "plan",
        "thinking",
        "system",
        "tool_result",
        "work_result",
    ]


def test_events_for_started_run_explains_in_progress() -> None:
    item = AgentRunHistoryItem(
        id="r2",
        workflow_id="wf-1",
        message="проверить сроки",
        status="started",
    )
    kinds = [event["type"] for event in _events_for_run(item)]
    assert kinds[0] == "user_message"
    assert kinds[-1] == "system"
    assert _status_label("started") == "выполняется"
    assert _status_label("ok") == "готово"
