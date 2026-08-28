from app.api_client import ApiClient, ApiError
from app.chat.test_user import ZHALYBIN_USER_ID
from app.orchestrator.agents import MEETING_WORKFLOW_ID, REVISION_WORKFLOW_ID


class _UnauthorizedClient(ApiClient):
    def _request(self, *_args, **_kwargs):
        raise ApiError("Требуется авторизация", status_code=401)


def test_local_test_user_reads_orchestrator_agents() -> None:
    client = _UnauthorizedClient("http://127.0.0.1:9")
    client._user_id = ZHALYBIN_USER_ID
    board = client.get_workflow_board()
    ids = {agent.id for agent in board.agents}
    assert REVISION_WORKFLOW_ID in ids
    assert MEETING_WORKFLOW_ID in ids
    items = client.list_workflows()
    assert {item.id for item in items} == ids
    assert client.get_workflow(REVISION_WORKFLOW_ID).title
    assert client.list_agent_drafts() == []
    assert client.list_workflow_files(REVISION_WORKFLOW_ID).user_files == []
    assert client.list_agent_runs(REVISION_WORKFLOW_ID) == []


def test_local_workflow_files_without_user_id(tmp_path) -> None:
    from app.sdk_agent.files import seed_workflow_files

    client = _UnauthorizedClient("http://127.0.0.1:9")
    note = seed_workflow_files(client, REVISION_WORKFLOW_ID, str(tmp_path))
    assert "пустая" in note
    assert (tmp_path / "materials" / "manifest.json").is_file()


class _NotFoundClient(ApiClient):
    def _request(self, *_args, **_kwargs):
        raise ApiError("Workflow не найден", status_code=404)


def test_local_orchestrator_run_survives_missing_server_workflow() -> None:
    client = _NotFoundClient("http://127.0.0.1:9")
    client._user_id = ZHALYBIN_USER_ID
    started = client.start_local_agent_run(REVISION_WORKFLOW_ID, message="типовая задача")
    assert started.id
    assert started.workflow_id == REVISION_WORKFLOW_ID
    client.update_local_agent_run_events(REVISION_WORKFLOW_ID, started.id, [{"type": "note"}])
    finished = client.finish_local_agent_run(
        REVISION_WORKFLOW_ID,
        started.id,
        status="ok",
        answer="готово",
        message="типовая задача",
    )
    assert finished.status == "ok"
    assert finished.answer == "готово"


def test_other_user_still_sees_auth_error() -> None:
    client = _UnauthorizedClient("http://127.0.0.1:9")
    client._user_id = "ERP-USER"
    try:
        client.get_workflow_board()
    except ApiError as exc:
        assert exc.is_auth
    else:
        raise AssertionError("expected auth error")
