from main import _handoff_command, _ipc_command


def test_ipc_flag_uses_explicit_command() -> None:
    assert _ipc_command(["main.py", "--ipc", "open-workflow:wf-1|run-2"]) == "open-workflow:wf-1|run-2"
    assert _ipc_command(["main.py", "--ipc=raise"]) == "raise"


def test_ipc_flag_derives_open_workflow() -> None:
    assert (
        _ipc_command(["main.py", "--ipc", "--open-workflow=wf-9", "--open-run=r1"])
        == "open-workflow:wf-9|r1"
    )


def test_no_ipc_flag() -> None:
    assert _ipc_command(["main.py", "--open-workflow=wf-1"]) is None


def test_handoff_command() -> None:
    assert _handoff_command(["main.py"]) == "raise"
    assert _handoff_command(["main.py", "--open-workflow=wf-1"]) == "open-workflow:wf-1"
    assert (
        _handoff_command(["main.py", "--open-workflow=wf-1", "--start-demo"])
        == "start-demo:wf-1"
    )
