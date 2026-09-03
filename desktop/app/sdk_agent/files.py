from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from app.api_client import ApiClient, WorkflowFileItem, WorkflowRecord

AGENT_BRIEF_RELATIVE = "materials/agent.md"
AGENTS_MD_RELATIVE = "AGENTS.md"


def _clear_dir_contents(path: Path) -> None:
    try:
        if not path.is_dir():
            return
        for entry in path.iterdir():
            try:
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    entry.unlink()
            except OSError:
                pass
    except OSError:
        pass


# Office-document outputs the agent creates at the workspace root
# (excel.create_workbook, report.export_document, ...). They are the deliverables
# of a single run and are persisted to the DB when relevant, so leftovers from a
# previous run must not linger in the working dir — otherwise list_files() and
# the "attach a file" flow surface stale files that "shouldn't be there".
_STALE_OUTPUT_SUFFIXES = frozenset(
    {".xlsx", ".xls", ".xlsm", ".csv", ".docx", ".doc", ".pdf", ".pptx", ".ppt", ".odt", ".rtf"}
)
# Never delete these root files even if the suffix matches (re-seeded/knowledge).
_KEEP_ROOT_NAMES = frozenset({"agents.md", "keepknowledgefile", "keep_knowledge_file"})


def _clear_stale_outputs(base: Path) -> None:
    try:
        if not base.is_dir():
            return
        for entry in base.iterdir():
            try:
                if not entry.is_file():
                    continue
                if entry.name.lower() in _KEEP_ROOT_NAMES:
                    continue
                if entry.suffix.lower() in _STALE_OUTPUT_SUFFIXES:
                    entry.unlink()
            except OSError:
                pass
    except OSError:
        pass


def reset_run_scratch(cwd: str, *, clear_attachments: bool = True) -> None:
    """Delete leftover per-run temp files so they don't accumulate between runs.

    The per-workflow workspace is reused across runs, so intermediate artifacts
    would otherwise pile up and leak into the next run (stale attachments make the
    agent see files that "shouldn't be there").

    Always clears ``tool_results/`` (large tool-result dumps). When
    ``clear_attachments`` is True it also clears ``materials/attachments/`` and
    removes leftover output documents (xlsx/docx/pdf/...) from the workspace
    root left by previous runs. The caller keeps it False on a resume/follow-up
    so a file attached or produced in an earlier turn of the same conversation
    survives. Permanent knowledge in ``materials/`` and the run journal are left
    untouched (they are re-seeded from the DB anyway).
    """
    base = Path((cwd or "").strip() or ".")
    _clear_dir_contents(base / "tool_results")
    if clear_attachments:
        _clear_dir_contents(base / "materials" / "attachments")
        # Independent run: also drop leftover output documents from prior runs
        # so they don't accumulate at the workspace root or confuse file lookup.
        _clear_stale_outputs(base)


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
    playbook = {}
    if isinstance(workflow.local_run, dict):
        raw_playbook = workflow.local_run.get("playbook")
        if isinstance(raw_playbook, dict):
            playbook = raw_playbook
    instructions = str(playbook.get("instructions") or "").strip()
    if instructions:
        parts.extend(["", "## Инструкция запуска", instructions])
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
            "Если нужен файл, спроси через askQuestion с needsFile=true."
        )
    return (
        "Прочитай materials/manifest.json, затем нужные файлы. "
        "Если документа нет, спроси через askQuestion с needsFile=true."
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
