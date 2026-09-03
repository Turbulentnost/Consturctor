from types import SimpleNamespace

from app.services.agent_runtime import _playbook_plan_text
from app.services.agent_runs import SDK_DEAD_ANSWER, effective_run_status, slim_run_events
from app.services.workflows.cursor_tools import (
    clear_tool_context,
    current_history_run_id,
    set_tool_context,
)


def test_slim_run_events_keeps_tool_and_work_result() -> None:
    stored = slim_run_events(
        [
            {"type": "run", "run_id": "bridge"},
            {
                "type": "tool_result",
                "text": "users.subordinates\n6 человек",
                "tool": "users.subordinates",
                "result": {"users": [{"fio": "Иванов"}], "count": 1},
            },
            {
                "type": "work_result",
                "text": "Сводка готова",
                "files": ["artifacts/RESULT.md"],
                "actions": ["открыть отчёт"],
                "notifications": ["руководителю"],
            },
            {"type": "done"},
        ]
    )
    assert [item["type"] for item in stored] == ["tool_result", "work_result"]
    assert stored[0]["tool"] == "users.subordinates"
    assert stored[0]["result"]["count"] == 1
    assert stored[1]["files"] == ["artifacts/RESULT.md"]
    assert stored[1]["actions"] == ["открыть отчёт"]
    assert stored[1]["notifications"] == ["руководителю"]


def test_slim_run_events_keeps_decision_and_plan() -> None:
    stored = slim_run_events(
        [
            {"type": "plan", "title": "План", "text": "s1 — Список"},
            {"type": "decision", "text": "читаю подчинённых"},
            {"type": "thinking", "text": "сверяю штатку"},
        ]
    )
    assert [item["type"] for item in stored] == ["plan", "decision", "thinking"]
    assert stored[0]["text"] == "s1 — Список"


def test_playbook_plan_text_from_steps() -> None:
    workflow = SimpleNamespace(local_run={})
    text = _playbook_plan_text(
        {
            "goal": "Контроль сектора",
            "steps": [
                {"id": "s1", "title": "Список", "action": "вызови users.subordinates"},
            ],
        },
        workflow,
    )
    assert "Цель: Контроль сектора" in text
    assert "s1 — Список" in text
    assert "users.subordinates" in text


def test_history_run_id_from_tool_context() -> None:
    set_tool_context("bridge-1", "user-1", "history-9")
    try:
        assert current_history_run_id() == "history-9"
    finally:
        clear_tool_context()
    assert current_history_run_id() == ""


def test_notify_send_writes_history_run_id(monkeypatch) -> None:
    from app.services.workflows.cursor_tools import _invoke_notify_send

    captured: dict = {}

    class _Item:
        id = "n1"
        recipient_user_id = "u2"
        title = "Просрочка"

    monkeypatch.setattr(
        "app.services.notifications.service.create_notification",
        lambda db, sender_user_id, payload: captured.update(
            {"sender": sender_user_id, "run_id": payload.run_id, "workflow_id": payload.workflow_id}
        )
        or _Item(),
    )
    from app.services.notifications.hub import hub as notify_hub

    monkeypatch.setattr(notify_hub, "schedule_push", lambda *_a, **_k: True)
    monkeypatch.setattr(
        "app.services.notifications.service.payload_dict",
        lambda item: {"id": item.id, "title": item.title, "type": "notification"},
    )
    set_tool_context("bridge-1", "user-1", "run-hist")
    try:
        result = _invoke_notify_send(
            {
                "user_id": "u2",
                "title": "Просрочка",
                "body": "есть просрочки",
                "workflow_id": "wf-1",
            }
        )
    finally:
        clear_tool_context()
    assert result["ok"] is True
    assert result["saved"] is True
    assert "delivered" not in result
    assert captured["run_id"] == "run-hist"
    assert captured["workflow_id"] == "wf-1"
    assert captured["sender"] == "user-1"


def test_effective_run_status_success_needs_result() -> None:
    assert effective_run_status("ok", "сводка готова") == "ok"
    assert effective_run_status("ok", "") == "canceled"
    assert effective_run_status("ok", "Остановлено пользователем") == "canceled"
    assert effective_run_status("canceled", "") == "canceled"
    assert effective_run_status("started", "", in_flight=True) == "started"
    assert effective_run_status("started", "", in_flight=False) == "canceled"
    assert effective_run_status("error", SDK_DEAD_ANSWER) == "canceled"
    assert effective_run_status("error", "инструмент вернул 500") == "error"


def test_slim_run_events_keeps_timing_markers() -> None:
    stored = slim_run_events(
        [
            {"type": "thinking", "text": "думаю", "at": "2026-09-02T08:00:00Z"},
            {
                "type": "human_wait",
                "wait": "question",
                "requestId": "q1",
                "at": "2026-09-02T08:00:10Z",
            },
            {
                "type": "human_reply",
                "wait": "question",
                "requestId": "q1",
                "at": "2026-09-02T08:01:10Z",
            },
        ]
    )
    assert [item["type"] for item in stored] == ["thinking", "human_wait", "human_reply"]
    assert stored[1]["requestId"] == "q1"
    assert stored[1]["at"] == "2026-09-02T08:00:10Z"


def test_compute_run_timing_splits_agent_and_human() -> None:
    from datetime import datetime, timezone

    from app.services.agent_runs import compute_run_timing

    started = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 9, 2, 8, 3, tzinfo=timezone.utc)
    timing = compute_run_timing(
        [
            {"type": "thinking", "at": "2026-09-02T08:00:05Z"},
            {"type": "question", "at": "2026-09-02T08:00:20Z"},
            {"type": "human_reply", "at": "2026-09-02T08:01:20Z"},
            {"type": "thinking", "at": "2026-09-02T08:01:21Z"},
        ],
        started_at=started,
        finished_at=finished,
    )
    assert timing["agent_work_ms"] == 120_000
    assert timing["human_wait_ms"] == 60_000
    assert timing["open_segment"] == ""


def test_compute_run_timing_holds_through_tool_request() -> None:
    from datetime import datetime, timezone

    from app.services.agent_runs import compute_run_timing

    started = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 9, 2, 8, 3, tzinfo=timezone.utc)
    timing = compute_run_timing(
        [
            {"type": "thinking", "at": "2026-09-02T08:00:05Z"},
            {"type": "question", "at": "2026-09-02T08:00:20Z"},
            {"type": "tool_request", "at": "2026-09-02T08:00:21Z"},
            {"type": "human_wait", "wait": "question", "at": "2026-09-02T08:00:21Z"},
            {"type": "human_reply", "wait": "question", "at": "2026-09-02T08:01:20Z"},
            {"type": "thinking", "at": "2026-09-02T08:01:21Z"},
        ],
        started_at=started,
        finished_at=finished,
    )
    assert timing["human_wait_ms"] == 60_000
    assert timing["agent_work_ms"] == 120_000
