from __future__ import annotations

from app.models.workflow import Workflow
from app.services.cursor_chat_runtime import (
    _generic_playbook_from_workflow,
    resolve_playbook_for_chat,
)


def test_generic_playbook_from_document() -> None:
    wf = Workflow(
        id="w1",
        title="Отчётность",
        document_text="Сформировать отчёт и положить на рабочий стол.",
        plan_json={"goal": "Автоматизировать отчёт", "constraints": ["Без ручного Excel"]},
    )
    pb = _generic_playbook_from_workflow(wf)
    assert "отчёт" in pb["instructions"].casefold()
    assert pb["from_regulation"] is True


def test_resolve_chat_tool_names_act_full_catalog() -> None:
    from app.services.cursor_chat_runtime import resolve_chat_tool_names

    wf = Workflow(
        id="w-act",
        title="ACT",
        document_name="ACT_REGISTRY.md",
        document_text="Document_ТД_Поручения",
        plan_json={
            "agent_route": {
                "handler": "act_porucheniya_registry",
                "tools": ["onec.act_porucheniya_registry", "excel.create_workbook"],
            }
        },
        local_run={"seed": "act_porucheniya", "tools": ["excel.create_workbook"]},
    )
    names = resolve_chat_tool_names(wf)
    assert "document.write_docx" in names
    assert "files.rename" in names
    assert "onec.act_porucheniya_registry" in names


def test_resolve_playbook_prefers_local_run() -> None:
    wf = Workflow(
        id="w2",
        title="ACT",
        local_run={"playbook": {"instructions": "Регламент ACT", "example_run": "—"}},
    )
    pb = resolve_playbook_for_chat(wf)
    assert pb["instructions"] == "Регламент ACT"