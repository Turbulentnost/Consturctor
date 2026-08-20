from app.models.workflow import Workflow
from app.services.act_registry_workflow import (
    regulation_playbook_for_workflow,
    workflow_uses_cursor_runtime,
)
from app.services.workflows.prompts import build_cursor_system_prompt, build_published_run_prompt


def test_regulation_in_system_prompt() -> None:
    system = build_cursor_system_prompt(
        regulation="# ACT\n\nПравило 1.",
        example_run="пример",
        title="ACT-реестр",
    )
    assert "РЕГЛАМЕНТ" in system
    assert "Правило 1" in system
    assert "constructor_tool" in system
    assert "КТО ТЫ" in system


def test_published_prompt_separates_task() -> None:
    full = build_published_run_prompt(
        instructions="ignored when regulation set",
        regulation="REG-001",
        example_run="ex",
        user_message="переименуй файл",
        title="T",
    )
    assert "REG-001" in full
    assert "переименуй файл" in full
    assert "ТЕКУЩАЯ ЗАДАЧА" in full
    assert full.index("переименуй файл") < full.index("REG-001")


def test_act_workflow_uses_cursor_runtime() -> None:
    wf = Workflow(
        id="w1",
        title="ACT",
        document_name="ACT_REGISTRY.md",
        document_text="Document_ТД_Поручения",
        local_run={"execution_backend": "cursor", "seed": "act_porucheniya"},
    )
    assert workflow_uses_cursor_runtime(wf) is True
    pb = regulation_playbook_for_workflow(wf)
    assert "Document_ТД_Поручения" in pb["instructions"]
