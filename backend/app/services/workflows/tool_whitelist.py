"""Runtime tool whitelist: what the playbook actually needs, not the whole catalog."""

from __future__ import annotations

from typing import Any

_OFFICE_READ_TRIGGERS = frozenset(
    {
        "onec.download_artifact",
        "excel.read_workbook",
        "excel.list_files",
        "onec.erp_assignments",
        "onec.list_attachments",
        "onec.read_attachment",
    }
)


def _ensure_office_reader(names: list[str], add) -> None:
    if names and any(item in _OFFICE_READ_TRIGGERS for item in names):
        add("office.read_file")


# Cursor SDK built-ins. Published / demo-with-draft agents should not wander the workspace.
CURSOR_BUILTIN_TOOLS = frozenset(
    {
        "read",
        "grep",
        "glob",
        "ls",
        "shell",
        "edit",
        "delete",
        "applyAgentDiff",
        "code.run_python",
        "write",
    }
)


def collect_runtime_whitelist(
    *,
    row: Any = None,
    local: dict[str, Any] | None = None,
    playbook: dict[str, Any] | None = None,
    plan: dict[str, Any] | None = None,
) -> list[str]:
    """Tools declared by playbook steps / demo, not the fat domain pack.

    Order of evidence:
    1. playbook.tools + tools named on playbook/draft steps + live demo tools
    2. plan.runtime.tools if the playbook is still empty
    3. stored local_run.tools if nothing else is known
    """
    data = local if isinstance(local, dict) else {}
    if not data and row is not None:
        raw = getattr(row, "local_run", None)
        data = raw if isinstance(raw, dict) else {}
    book = playbook if isinstance(playbook, dict) else {}
    if not book:
        raw_book = data.get("playbook")
        book = raw_book if isinstance(raw_book, dict) else {}
    draft = data.get("playbook_draft") if isinstance(data.get("playbook_draft"), dict) else {}
    plan_data = plan if isinstance(plan, dict) else {}
    if not plan_data and row is not None:
        raw_plan = getattr(row, "plan_json", None)
        plan_data = raw_plan if isinstance(raw_plan, dict) else {}

    names: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        name = str(value or "").strip()
        if not name or name in seen or name in CURSOR_BUILTIN_TOOLS:
            return
        seen.add(name)
        names.append(name)

    def add_all(values: object) -> None:
        if isinstance(values, str):
            add(values)
            return
        if not isinstance(values, (list, tuple, set)):
            return
        for item in values:
            add(item)

    add_all(book.get("tools"))
    add_all(data.get("live_tools_invoked"))
    for blob in (book, draft):
        for step in blob.get("steps") or []:
            if not isinstance(step, dict):
                continue
            add(step.get("tool") or step.get("tool_name"))
            add_all(step.get("tool_candidates"))

    _ensure_office_reader(names, add)
    if names:
        return names

    runtime = plan_data.get("runtime") if isinstance(plan_data.get("runtime"), dict) else {}
    add_all(runtime.get("tools"))
    _ensure_office_reader(names, add)
    if names:
        return names

    add_all(data.get("tools"))
    _ensure_office_reader(names, add)
    return names


def store_whitelist(local: dict[str, Any], names: list[str]) -> dict[str, Any]:
    payload = dict(local or {})
    if names:
        payload["tools"] = list(names)
    return payload
