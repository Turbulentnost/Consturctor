from __future__ import annotations

import json
import re
from pathlib import Path

from app.api_client import ApiClient, WorkflowFileItem, WorkflowRecord

AGENT_BRIEF_RELATIVE = "materials/agent.md"
AGENTS_MD_RELATIVE = "AGENTS.md"


def write_workspace_note(cwd: str, relative: str, text: str) -> str:
    root = Path(cwd)
    target = (root / relative).resolve()
    if root.resolve() not in target.parents and target != root.resolve():
        raise ValueError(f"refusing to write outside workspace: {relative}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return Path(relative).as_posix()


def seed_agent_brief(cwd: str, workflow: WorkflowRecord, *, extra: str = "") -> str:
    """Write passport, plan, and optional design brief into materials/agent.md."""
    title = (workflow.title or "агент").strip() or "агент"
    parts: list[str] = [
        f"# {title}",
        "",
        "Язык: русский. Размышления, вопросы, значения JSON и файлы пиши по-русски.",
    ]
    notes = (workflow.notes or "").strip()
    if notes:
        parts.extend(["", "## Заметки", notes])
    document = (workflow.document_text or "").strip()
    if document:
        name = (workflow.document_name or "документ").strip() or "документ"
        parts.extend(["", f"## Документ ({name})", document])
    plan = workflow.plan
    if plan is not None:
        parts.extend(["", "## План"])
        if plan.title:
            parts.append(f"Название: {plan.title}")
        if plan.goal:
            parts.append(f"Цель: {plan.goal}")
        if plan.constraints:
            parts.append("Ограничения:")
            parts.extend(f"- {item}" for item in plan.constraints if str(item).strip())
        if plan.out_of_scope:
            parts.append("Вне объема:")
            parts.extend(f"- {item}" for item in plan.out_of_scope if str(item).strip())
        steps = plan.steps or []
        if steps:
            parts.append("Шаги:")
            for step in steps:
                text = step.action or step.title
                label = step.id or step.title
                if text:
                    parts.append(f"- {label}: {text}")
                if step.done_when:
                    parts.append(f"  Готово когда: {step.done_when}")
        if plan.test_criteria:
            parts.append("Критерии проверки:")
            parts.extend(f"- {item}" for item in plan.test_criteria if str(item).strip())
        if plan.raw_text:
            parts.extend(["", "Исходный паспорт:", plan.raw_text.strip()])
    last = (workflow.last_result or "").strip()
    if last:
        parts.extend(["", "## Последний успешный прогон", last[:12000]])
    extra_text = (extra or "").strip()
    if extra_text:
        parts.extend(["", "## Бриф проектирования", extra_text])
    from app.sdk_agent.prompt import known_design_facts

    facts = known_design_facts(workflow)
    if facts:
        parts.extend(["", "## Уже известно"])
        parts.extend(f"- {item}" for item in facts)
    body = "\n".join(parts).strip() + "\n"
    return write_workspace_note(cwd, AGENT_BRIEF_RELATIVE, body)


def seed_agents_md(cwd: str) -> str:
    from app.sdk_agent.prompt import AGENTS_MD

    return write_workspace_note(cwd, AGENTS_MD_RELATIVE, AGENTS_MD)


def workspace_file_pointer() -> str:
    return (
        "Прочитай AGENTS.md, materials/agent.md и materials/manifest.json. "
        "Детали в этих файлах, не в этом сообщении."
    )


def prepare_sdk_workspace(
    api: ApiClient,
    workflow_id: str,
    cwd: str,
    *,
    workflow: WorkflowRecord | None = None,
    extra_brief: str = "",
) -> str:
    seed_agents_md(cwd)
    seed_workflow_files(api, workflow_id, cwd)
    if workflow is not None:
        seed_agent_brief(cwd, workflow, extra=extra_brief)
    return workspace_file_pointer()


def seed_workflow_files(api: ApiClient, workflow_id: str, cwd: str) -> str:
    """Materialize persistent agent documents into the Cursor SDK workspace."""
    wid = (workflow_id or "").strip()
    if not wid:
        return ""
    root = Path(cwd)
    materials = root / "materials"
    materials.mkdir(parents=True, exist_ok=True)
    files = api.list_workflow_files(wid)
    manifest: list[dict] = []
    for index, item in enumerate(files.user_files, start=1):
        entry = _materialize_file(api, wid, item, materials, index=index)
        if entry:
            manifest.append(entry)
    manifest_path = materials / "manifest.json"
    manifest_path.write_text(
        json.dumps({"files": manifest}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if not manifest:
        return (
            "Прочитай materials/manifest.json. База документов пустая. "
            "Если нужен файл, спроси через askQuestion."
        )
    return (
        "Прочитай materials/manifest.json, затем нужные файлы. "
        "Если документа нет, спроси через askQuestion."
    )


def _materialize_file(
    api: ApiClient,
    workflow_id: str,
    item: WorkflowFileItem,
    materials: Path,
    *,
    index: int,
) -> dict | None:
    if not item.id:
        return None
    filename = _safe_filename(item.filename or f"file-{index}")
    target = materials / f"{index:03d}_{filename}"
    api.download_workflow_file_to(workflow_id, item.id, target)
    text_payload = api.workflow_file_text(workflow_id, item.id)
    text = str(text_payload.get("text") or "").strip()
    text_path = ""
    if text:
        extracted = target.with_suffix(target.suffix + ".txt")
        extracted.write_text(text, encoding="utf-8")
        text_path = extracted.relative_to(materials.parent).as_posix()
    return {
        "id": item.id,
        "filename": item.filename,
        "path": target.relative_to(materials.parent).as_posix(),
        "extracted_text_path": text_path,
        "mime_type": item.mime_type,
        "kind": item.kind,
        "size": item.size,
        "sha256": item.sha256,
        "summary": item.summary or str(text_payload.get("summary") or ""),
        "source": item.source,
        "scope": item.scope,
    }


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-zА-Яа-я0-9_.() -]", "_", (name or "file").strip())
    cleaned = cleaned.strip(" .") or "file"
    return cleaned[:180]
