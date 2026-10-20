import queue
from types import SimpleNamespace

from app.services import sessions
from app.services.triggers import headless, runner


def test_serve_declines_writes_answers_questions_and_returns_own_result():
    lines: queue.Queue = queue.Queue()
    for item in (
        {"type": "event", "runId": "r1", "payload": {}},
        {"type": "hitl", "runId": "r1", "requestId": "h1", "tool": "onec.odata_patch"},
        {"type": "question", "runId": "r1", "requestId": "q1", "question": "Какой период?"},
        {"type": "result", "runId": "other", "status": "ok"},
        {"type": "result", "runId": "r1", "status": "ok", "runRef": "run-9", "answer": "готово"},
    ):
        lines.put(item)
    sent: list[dict] = []

    outcome = headless._serve(lines, sent.append, run_id="r1", deadline=headless.time.monotonic() + 5)

    assert outcome["runRef"] == "run-9"
    assert {"type": "hitl", "requestId": "h1", "approved": False} in sent
    assert any(cmd["type"] == "answer" and cmd["requestId"] == "q1" for cmd in sent)


def test_serve_reports_dead_sidecar():
    lines: queue.Queue = queue.Queue()
    lines.put(None)
    outcome = headless._serve(lines, lambda _cmd: None, run_id="r1", deadline=headless.time.monotonic() + 5)
    assert outcome["type"] == "error"


def test_serve_reports_a_silent_sidecar_as_stalled():
    lines: queue.Queue = queue.Queue()
    lines.put({"type": "event", "runId": "r1", "payload": {}})
    outcome = headless._serve(
        lines, lambda _cmd: None, run_id="r1", deadline=headless.time.monotonic() + 5, silence_s=0.2
    )
    assert outcome == {"type": "stalled"}


def test_hung_run_is_started_again_once(monkeypatch):
    attempts: list[int] = []

    def fake_run(**_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise headless.HeadlessRunStalled("молчал")
        return {"ok": True, "status": "ok"}

    monkeypatch.setattr(headless, "unavailable_reason", lambda: "")
    monkeypatch.setattr(headless, "_run", fake_run)
    out = headless.run_headless(user_id="u1", workflow_id="wf-1", message="m")
    assert out["ok"] and len(attempts) == 2
    assert not headless.is_running("wf-1")


def test_run_that_hangs_twice_fails(monkeypatch):
    def fake_run(**_kwargs):
        raise headless.HeadlessRunStalled("молчал")

    monkeypatch.setattr(headless, "unavailable_reason", lambda: "")
    monkeypatch.setattr(headless, "_run", fake_run)
    try:
        headless.run_headless(user_id="u1", workflow_id="wf-1", message="m")
    except headless.HeadlessRunStalled:
        pass
    else:
        raise AssertionError("expected HeadlessRunStalled")


def test_server_client_never_takes_the_desktop_session(monkeypatch):
    calls: list[tuple] = []
    fake = SimpleNamespace(set=lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(sessions, "_redis", lambda: fake)
    sessions.replace_session("u1", "sid", client="server")
    sessions.mark_online("u1", "sid", client="server")
    assert calls == []
    assert sessions.normalize_client("server") == "server"


def _trigger(**extra):
    base = dict(
        id="t1",
        workflow_id="wf-1",
        owner_user_id="u1",
        message="Плановая проверка",
        last_evidence="",
        condition_text="",
    )
    base.update(extra)
    return SimpleNamespace(**base)


def _workflow(run_on_server=True):
    return SimpleNamespace(id="wf-1", title="Проверка", local_run={"run_on_server": run_on_server})


def test_start_on_server_fires_and_spawns_background_job(monkeypatch):
    fired: list[str] = []
    jobs: list[dict] = []
    monkeypatch.setattr(headless, "unavailable_reason", lambda: "")
    monkeypatch.setattr(headless, "is_running", lambda _wid: False)
    monkeypatch.setattr(runner, "_fresh_started_run", lambda _db, _wid: False)
    monkeypatch.setattr(runner, "mark_fired", lambda _db, **kw: fired.append(kw["trigger_id"]))

    class FakeThread:
        def __init__(self, *, target, kwargs, name, daemon):
            jobs.append(kwargs)

        def start(self):
            pass

    monkeypatch.setattr(runner.threading, "Thread", FakeThread)

    out = runner._start_on_server(None, _trigger(), _workflow())

    assert out == {"ok": True, "trigger_id": "t1", "dispatched": "server"}
    assert fired == ["t1"]
    assert jobs[0]["message"] == "Плановая проверка" and jobs[0]["workflow_id"] == "wf-1"


def test_start_on_server_falls_back_to_desktop_when_backend_cannot_run(monkeypatch):
    monkeypatch.setattr(headless, "unavailable_reason", lambda: "не найден node")
    assert runner._start_on_server(None, _trigger(), _workflow()) is None


def test_start_on_server_skips_overlapping_slot(monkeypatch):
    canceled: list[str] = []
    monkeypatch.setattr(headless, "unavailable_reason", lambda: "")
    monkeypatch.setattr(headless, "is_running", lambda _wid: True)
    monkeypatch.setattr(runner, "cancel_overlapping_slot", lambda _db, **kw: canceled.append(kw["trigger_id"]))
    out = runner._start_on_server(None, _trigger(), _workflow())
    assert out["reason"] == "already_running" and canceled == ["t1"]


def _yield_case(monkeypatch, *, reason: str, overdue_min: float, run_on_server: bool = True) -> bool:
    from datetime import datetime, timedelta, timezone

    from app.services.triggers import service

    now = datetime.now(timezone.utc)
    row = _trigger(fire_at=now - timedelta(minutes=overdue_min))
    db = SimpleNamespace(get=lambda _model, _id: _workflow(run_on_server))
    monkeypatch.setattr(headless, "unavailable_reason", lambda: reason)
    return service.yields_to_server_backend(db, row, now=now)


def test_stored_server_flag_does_not_make_backend_yield(monkeypatch):
    assert _yield_case(monkeypatch, reason="не найден node", overdue_min=1) is False


def test_capable_backend_takes_server_trigger(monkeypatch):
    assert _yield_case(monkeypatch, reason="", overdue_min=1) is False


def test_overdue_server_trigger_is_taken_by_any_backend(monkeypatch):
    assert _yield_case(monkeypatch, reason="не найден node", overdue_min=11) is False


def test_desktop_trigger_is_never_left(monkeypatch):
    assert _yield_case(monkeypatch, reason="не найден node", overdue_min=1, run_on_server=False) is False


def test_runs_on_server_flag():
    assert runner.runs_on_server(_workflow(True)) is False
    assert runner.runs_on_server(_workflow(False)) is False
