from __future__ import annotations

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
PYBRIDGE = ROOT / "desktop-electron" / "pybridge"
if str(PYBRIDGE) not in sys.path:
    sys.path.insert(0, str(PYBRIDGE))

from agent_sidecar import (  # noqa: E402
    ActiveRun,
    Sidecar,
    _is_trigger_command,
    _sdk_run_alive,
)


def _thread(alive: bool) -> SimpleNamespace:
    return SimpleNamespace(is_alive=lambda: alive)


def _process(code: int | None) -> SimpleNamespace:
    return SimpleNamespace(poll=lambda: code)


def _active(
    *,
    run_id: str = "run-1",
    workflow_id: str = "wf-1",
    alive: bool = True,
    process_code: int | None = None,
    has_process: bool = False,
) -> ActiveRun:
    bridge = SimpleNamespace(_process=_process(process_code) if has_process else None)
    active = ActiveRun(run_id, SimpleNamespace(bind=lambda **_k: None), threading.Event(), bridge)
    active.workflow_id = workflow_id
    active.dedup_key = f"run:{workflow_id}"
    active.thread = _thread(alive)
    return active


def test_is_trigger_command() -> None:
    assert _is_trigger_command({"source": "trigger"}) is True
    assert _is_trigger_command({"triggerId": "tr-1"}) is True
    assert _is_trigger_command({"trigger_id": "tr-1"}) is True
    assert _is_trigger_command({"source": "chat"}) is False
    assert _is_trigger_command({}) is False


def test_sdk_run_alive() -> None:
    assert _sdk_run_alive(_active(alive=True)) is True
    assert _sdk_run_alive(_active(alive=False)) is False
    dead_proc = _active(alive=True, has_process=True, process_code=1)
    assert _sdk_run_alive(dead_proc) is False
    live_proc = _active(alive=True, has_process=True, process_code=None)
    assert _sdk_run_alive(live_proc) is True
    no_thread = _active(alive=True)
    no_thread.thread = None
    assert _sdk_run_alive(no_thread) is False


def test_trigger_overlap_cancels_when_sdk_alive() -> None:
    sidecar = Sidecar()
    canceled: list[tuple[str, str, str]] = []
    sidecar._api = SimpleNamespace(
        cancel_overlapping_slot=lambda workflow_id, trigger_id, answer="": canceled.append(
            (workflow_id, trigger_id, answer)
        )
    )
    live = _active(run_id="live-1", alive=True)
    sidecar._active[live.run_id] = live
    sidecar._run_safe = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not start"))
    sidecar.start(
        "run",
        {
            "id": "run-dup",
            "workflowId": "wf-1",
            "source": "trigger",
            "triggerId": "tr-51",
        },
    )
    assert "run-dup" not in sidecar._active
    assert list(sidecar._active) == ["live-1"]
    assert canceled == [("wf-1", "tr-51", "Агент уже выполняется")]


def test_chat_duplicate_does_not_cancel_slot() -> None:
    sidecar = Sidecar()
    canceled: list[tuple] = []
    sidecar._api = SimpleNamespace(
        cancel_overlapping_slot=lambda *args, **kwargs: canceled.append((args, kwargs))
    )
    live = _active(run_id="live-1", alive=True)
    sidecar._active[live.run_id] = live
    sidecar._run_safe = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not start"))
    sidecar.start(
        "run",
        {"id": "run-dup", "workflowId": "wf-1", "source": "chat"},
    )
    assert canceled == []
    assert "run-dup" not in sidecar._active
    assert list(sidecar._active) == ["live-1"]


def test_trigger_overlap_replaces_dead_sdk() -> None:
    sidecar = Sidecar()
    canceled: list[tuple] = []
    sidecar._api = SimpleNamespace(
        cancel_overlapping_slot=lambda *args, **kwargs: canceled.append((args, kwargs))
    )
    stale = _active(run_id="stale-1", alive=False)
    sidecar._active[stale.run_id] = stale
    ran: list[str] = []
    sidecar._run_safe = lambda kind, command, active: ran.append(active.run_id)
    sidecar.start(
        "run",
        {
            "id": "run-next",
            "workflowId": "wf-1",
            "source": "trigger",
            "triggerId": "tr-51",
        },
    )
    assert "stale-1" not in sidecar._active
    assert "run-next" in sidecar._active
    assert canceled == []
    sidecar._active["run-next"].thread.join(timeout=2)
    assert ran == ["run-next"]


def test_fail_unbacked_started_closes_stale_as_error() -> None:
    sidecar = Sidecar()
    finished: list[tuple] = []

    class _Api:
        def list_agent_runs(self, workflow_id: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(id="old-started", status="started")]

        def finish_local_agent_run(self, workflow_id, run_id, *, status, answer, **_kw) -> None:
            finished.append((workflow_id, run_id, status, answer))

    sidecar._api = _Api()
    sidecar._fail_unbacked_started("wf-1")
    assert finished == [("wf-1", "old-started", "error", "Cursor SDK не отвечает")]


def test_fail_unbacked_started_skips_when_sdk_live() -> None:
    sidecar = Sidecar()
    finished: list[tuple] = []

    class _Api:
        def list_agent_runs(self, workflow_id: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(id="old-started", status="started")]

        def finish_local_agent_run(self, workflow_id, run_id, *, status, answer, **_kw) -> None:
            finished.append((workflow_id, run_id, status, answer))

    sidecar._api = _Api()
    live = _active(run_id="live-1", alive=True)
    sidecar._active[live.run_id] = live
    sidecar._fail_unbacked_started("wf-1", except_run_id="other")
    assert finished == []


def test_shutdown_finishes_hanging_started() -> None:
    sidecar = Sidecar()
    finished: list[tuple] = []

    class _Api:
        def list_agent_runs(self, workflow_id: str) -> list[SimpleNamespace]:
            return [SimpleNamespace(id="ghost", status="started")]

        def finish_local_agent_run(self, workflow_id, run_id, *, status, answer, **_kw) -> None:
            finished.append((workflow_id, run_id, status, answer))

    sidecar._api = _Api()
    active = _active(run_id="live-1", alive=True)
    active.history_run_id = "hist-1"
    sidecar._active[active.run_id] = active
    sidecar.shutdown()
    assert sidecar._active == {}
    assert ("wf-1", "hist-1", "error", "Cursor SDK не отвечает") in finished
    assert ("wf-1", "ghost", "error", "Cursor SDK не отвечает") in finished
    assert active.stop.is_set()
