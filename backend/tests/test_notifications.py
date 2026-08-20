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


def test_continue_prompt_requires_real_call_for_every_step() -> None:
    text = build_demo_continue_prompt(document_text="Следить за сроками")
    assert "закрывается вызовом инструмента" in text
    assert "не считается выполнением" in text


def test_notify_step_gets_notify_tool_as_candidate() -> None:
    from app.services.workflows.cursor_tools import step_candidates_block
    from app.services.workflows.playbook_validation import attach_tool_candidates

    draft = attach_tool_candidates(
        {
            "steps": [
                {
                    "id": "s1",
                    "title": "Сообщить получателю",
                    "system": "constructor",
                    "entity": "notification",
                    "operation": "notify",
                }
            ]
        }
    )

    assert "notify.send" in step_candidates_block(draft)


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
        {"id": "n1", "ok": True, "saved": True, "title": "Просрочка"},
    )
    assert "уведомление" in text.casefold()
    assert "готово · уведомление на компьютер" not in text.casefold()
    assert "{" not in text


def test_format_notify_failure_series() -> None:
    text = _format_tool_output(
        "notify.send",
        {
            "id": "n1",
            "ok": True,
            "saved": True,
            "title": "План серии: серия не построена, встречи не записаны",
        },
    )
    assert "не удалась" in text.casefold()
