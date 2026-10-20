from types import SimpleNamespace

from app.services.agent_runtime import _playbook_plan_text
from app.services.agent_runs import (
    ANSWER_MAX_CHARS,
    MISSING_WORK_RESULT_ANSWER,
    SDK_DEAD_ANSWER,
    clip_answer,
    effective_run_status,
    is_successful_work_answer,
    slim_run_events,
    slim_run_context,
    slim_run_metrics,
)
from app.services.workflows.cursor_tools import (
    clear_tool_context,
    current_history_run_id,
    set_tool_context,
)


def test_slim_run_events_keeps_spaces_between_stream_tokens() -> None:
    stored = slim_run_events(
        [
            {"type": "assistant", "text": "Нужны"},
            {"type": "assistant", "text": " "},
            {"type": "assistant", "text": "Мегрелишвили"},
            {"type": "thinking", "text": "свер"},
            {"type": "thinking", "text": "яю"},
            {"type": "tool_call", "tool": "calendar.show_meetings", "arguments": {"day": "завтра"}},
            {"type": "assistant", "text": "Готово"},
        ]
    )
    assert [item["type"] for item in stored] == ["assistant", "thinking", "tool_call", "assistant"]
    assert stored[0]["text"] == "Нужны Мегрелишвили"
    assert stored[1]["text"] == "сверяю"
    assert stored[3]["text"] == "Готово"


def test_slim_run_metrics_keeps_numbers_only() -> None:
    stored = slim_run_metrics(
        [
            {"t": 10, "cpu": 1.5, "ram": 2, "gpu": None, "note": "x"},
            "bad",
            {"cpu": 1},
        ]
    )
    assert stored == [{"t": 10.0, "cpu": 1.5, "ram": 2.0}]


def test_slim_run_metrics_keeps_spike_with_processes() -> None:
    stored = slim_run_metrics(
        [
            {
                "t": 20,
                "cpu": 40,
                "spike": {
                    "marks": [
                        {"metric": "cpu", "value": 40, "baseline": 2},
                        {"metric": "gen", "value": 9, "baseline": 1},
                        {"metric": "ram", "value": "x", "baseline": 1},
                    ],
                    "processes": [{"pid": 7, "name": "node.exe", "cpu": 39.5, "ram_mb": 300, "gpu": None, "disk": 0.1}, "bad"],
                },
            },
            {"t": 21, "cpu": 3, "spike": {"marks": [{"metric": "gen", "value": 1, "baseline": 0}]}},
        ]
    )
    assert stored[0]["spike"] == {
        "marks": [{"metric": "cpu", "value": 40.0, "baseline": 2.0}],
        "processes": [{"pid": 7, "name": "node.exe", "cpu": 39.5, "ram_mb": 300.0, "gpu": None, "disk": 0.1}],
    }
    assert "spike" not in stored[1]


def test_slim_run_context_keeps_valid_ranges_and_clips_text() -> None:
    stored = slim_run_context(
        {
            "items": {
                "tools": {"type": "tools", "label": "Инструменты", "chars": 40, "text": "a, b"},
                "1:user": {"turn": 1, "type": "user", "label": "Промпт", "chars": 5000, "text": "x" * 5000},
                "1:s1": {"turn": 1, "type": "weird", "label": "?", "chars": 3, "text": "abc"},
                "bad": {"type": "user", "chars": "many"},
            },
            "order": ["tools", "1:user", "1:s1", "bad", "missing"],
            "snapshots": [
                {"seq": 1, "turn": 1, "kind": "user", "reason": "промпт", "from": 0, "to": 1, "usage": {"inputTokens": 9, "x": "y"}},
                {"seq": 2, "turn": 1, "kind": "thinking", "reason": "шаг", "from": 0, "to": 5},
            ],
        }
    )
    assert stored["order"] == ["1:user", "1:s1"]
    assert len(stored["items"]["1:user"]["text"]) == 1500
    assert stored["items"]["1:s1"]["type"] == "other"
    assert [snap["seq"] for snap in stored["snapshots"]] == [1]
    assert stored["snapshots"][0]["usage"] == {"inputTokens": 9}
    assert slim_run_context("junk") == {"items": {}, "order": [], "snapshots": []}


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


def test_slim_run_events_keeps_hitl_fields() -> None:
    stored = slim_run_events(
        [
            {
                "type": "tool_request",
                "text": "Нужно подтверждение: outlook.send_mail",
                "tool": "outlook.send_mail",
                "title": "Письмо",
                "request_id": "req-1",
                "confirm_only": True,
                "ok": True,
                "skipped": False,
                "status": "pending",
            }
        ]
    )
    assert stored[0]["request_id"] == "req-1"
    assert stored[0]["confirm_only"] is True
    assert stored[0]["ok"] is True
    assert stored[0]["skipped"] is False
    assert stored[0]["status"] == "pending"
    assert stored[0]["title"] == "Письмо"


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
    assert (
        effective_run_status(
            "error",
            "## WORK_RESULT\nУстный список совещаний\nTESTS: PASS",
        )
        == "ok"
    )
    assert (
        effective_run_status(
            "error",
            f"{MISSING_WORK_RESULT_ANSWER}\n\nОкно 06:55 — утреннее, до доклада 07:50",
        )
        == "error"
    )
    assert is_successful_work_answer("Агент упомянул WORK_RESULT и TESTS: PASS в ходе работы") is False
    assert is_successful_work_answer(MISSING_WORK_RESULT_ANSWER) is False


def test_slim_run_events_keeps_calendar_after_thinking_overflow() -> None:
    events = [{"type": "thinking", "text": f"step {index}"} for index in range(420)]
    events.append(
        {
            "type": "tool_call",
            "tool": "calendar.show_meetings",
            "arguments": {
                "meetings": [
                    {
                        "title": "СЗ 000014029",
                        "start": "2026-09-03T07:00:00+00:00",
                        "end": "2026-09-03T08:00:00+00:00",
                        "mark": "keep",
                    }
                ]
            },
        }
    )
    events.append({"type": "work_result", "text": "## WORK_RESULT\nПлан готов\nTESTS: PASS"})
    stored = slim_run_events(events)
    assert len(stored) <= 400
    tools = [item.get("tool") for item in stored]
    types = [item.get("type") for item in stored]
    assert "calendar.show_meetings" in tools
    assert "work_result" in types


def test_slim_run_events_keeps_hitl_after_thinking_overflow() -> None:
    events = [{"type": "thinking", "text": f"step {index}"} for index in range(420)]
    events.append(
        {
            "type": "hitl",
            "tool": "excel.create_workbook",
            "text": "Нужно подтверждение: excel.create_workbook",
            "requestId": "req-hitl",
            "confirm_only": True,
            "status": "pending",
        }
    )
    events.append({"type": "work_result", "text": "## WORK_RESULT\nГотово\nTESTS: PASS"})
    stored = slim_run_events(events)
    types = [item.get("type") for item in stored]
    assert "hitl" in types
    hitl = next(item for item in stored if item.get("type") == "hitl")
    assert hitl["requestId"] == "req-hitl"
    assert hitl["confirm_only"] is True
    assert hitl["status"] == "pending"


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


def test_compute_run_timing_chess_clock_multiple_switches() -> None:
    from datetime import datetime, timezone

    from app.services.agent_runs import compute_run_timing

    started = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 9, 2, 8, 5, tzinfo=timezone.utc)
    timing = compute_run_timing(
        [
            {"type": "thinking", "at": "2026-09-02T08:00:10Z"},
            {"type": "question", "at": "2026-09-02T08:00:30Z"},
            {"type": "human_reply", "at": "2026-09-02T08:01:30Z"},
            {"type": "thinking", "at": "2026-09-02T08:01:40Z"},
            {"type": "hitl", "at": "2026-09-02T08:02:00Z"},
            {"type": "human_reply", "at": "2026-09-02T08:03:00Z"},
            {"type": "thinking", "at": "2026-09-02T08:03:10Z"},
        ],
        started_at=started,
        finished_at=finished,
    )
    # agent: 0→30s + 1:30→2:00 + 3:00→5:00 = 30 + 30 + 120 = 180s
    # human: 0:30→1:30 + 2:00→3:00 = 60 + 60 = 120s
    assert timing["agent_work_ms"] == 180_000
    assert timing["human_wait_ms"] == 120_000
    assert timing["open_segment"] == ""


def test_compute_run_timing_keeps_agent_slice_before_human_wait() -> None:
    from datetime import datetime, timezone

    from app.services.agent_runs import compute_run_timing

    started = datetime(2026, 9, 2, 8, 0, tzinfo=timezone.utc)
    finished = datetime(2026, 9, 2, 8, 36, tzinfo=timezone.utc)
    timing = compute_run_timing(
        [
            {"type": "human_wait", "at": "2026-09-02T08:05:26Z"},
            {"type": "human_reply", "at": "2026-09-02T08:36:00Z"},
        ],
        started_at=started,
        finished_at=finished,
    )
    assert timing["agent_work_ms"] == 5 * 60_000 + 26_000
    assert timing["human_wait_ms"] == 30 * 60_000 + 34_000


def test_clip_answer_keeps_trailing_closure_check_block() -> None:
    block = '```closure-check\n{"assignments":[{"number":"АСТ00-00113"}]}\n```'
    clipped = clip_answer("x" * (ANSWER_MAX_CHARS + 500) + "\n\n" + block)

    assert len(clipped) <= ANSWER_MAX_CHARS
    assert clipped.endswith(block)


def test_clip_answer_leaves_short_answer() -> None:
    assert clip_answer("  ответ  ") == "ответ"
