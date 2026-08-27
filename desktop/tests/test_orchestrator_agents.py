from app.api_client import BoardAgent
from app.orchestrator.agents import (
    MEETING_WORKFLOW_ID,
    REVISION_WORKFLOW_ID,
    bound_workflow_id,
    is_local_workflow,
    local_board,
    local_workflow,
    match_board_agent,
)
from app.orchestrator.models import DEFINITIONS, MEETING_ID, REVISION_ID


def test_local_board_has_two_published_agents() -> None:
    board = local_board()
    assert [item.id for item in board.agents] == [REVISION_WORKFLOW_ID, MEETING_WORKFLOW_ID]
    assert all(item.kind == "workflow" and item.phase == "done" for item in board.agents)
    assert all(item.status == "active" for item in board.agents)


def test_local_workflow_has_passport() -> None:
    revision = local_workflow(REVISION_WORKFLOW_ID)
    meeting = local_workflow(MEETING_WORKFLOW_ID)
    assert revision is not None and revision.plan is not None
    assert meeting is not None and meeting.plan is not None
    assert "ревизион" in revision.title.casefold()
    assert "совещани" in meeting.title.casefold()
    assert is_local_workflow(REVISION_WORKFLOW_ID)
    assert not is_local_workflow("wf-backend")


def test_bind_prefers_published_board_agent() -> None:
    published = BoardAgent(
        id="wf-rk-1",
        kind="workflow",
        title="Работа ревизионной комиссии",
        status="active",
        phase="done",
    )
    definition = next(item for item in DEFINITIONS if item.id == REVISION_ID)
    assert match_board_agent(definition, [published]) == published
    assert bound_workflow_id(definition, [published]) == "wf-rk-1"
    meeting = next(item for item in DEFINITIONS if item.id == MEETING_ID)
    assert bound_workflow_id(meeting, [published]) == MEETING_WORKFLOW_ID
