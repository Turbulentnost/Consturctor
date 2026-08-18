from app.services.local_mcp import list_tools
from app.services.workflows.cursor_tools import (
    _format_tool_output,
    required_live_tools_from_plan,
    wants_notifications,
)
from app.services.workflows.plan_models import OpenQuestion, WorkflowPlan
from app.services.workflows.prompts import build_demo_continue_prompt, build_published_run_prompt


def test_notify_send_is_server_tool() -> None:
    tools = {item["name"]: item for item in list_tools()}
    assert tools["notify.send"]["execution"] == "server"
    assert tools["users.list"]["execution"] == "server"


def test_wants_notifications_from_answer() -> None:
    assert wants_notifications("Нужно слать уведомления руководителю")
    assert wants_notifications("notify.send получателю")
    assert not wants_notifications("просто сводка в чат")


def test_required_live_tools_include_notify() -> None:
    plan = WorkflowPlan(
        title="Контроль сроков",
        answered_questions=[
            OpenQuestion(id="q1", question="Как отдавать результат?", answer="слать уведомления")
        ],
    )
    assert "notify" in required_live_tools_from_plan(plan)


def test_continue_prompt_requires_notify_tool() -> None:
    text = build_demo_continue_prompt(document_text="Следить за сроками")
    assert "notify.send" in text


def test_published_prompt_requires_notify_when_asked() -> None:
    text = build_published_run_prompt(
        instructions="Пришли уведомление",
        example_run="notify.send",
        user_message="запусти",
    )
    assert "notify.send" in text


def test_format_notify_output() -> None:
    text = _format_tool_output(
        "notify.send",
        {"id": "n1", "ok": True, "delivered": "на компьютер получателя", "title": "Просрочка"},
    )
    assert "уведомление" in text.casefold()
    assert "{" not in text
