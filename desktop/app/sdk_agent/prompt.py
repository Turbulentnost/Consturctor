from __future__ import annotations

import re

from app.api_client import WorkflowRecord
from app.sdk_agent.tool_adapter import sdk_tool_specs

AGENTS_MD = """\
# Constructor local agent

Constructor tools are already connected as customTools. Do not look for project MCP or mcp.json.
Do not write that MCP was not found. Do not paste a tool-call JSON in chat: call the tool.
Read materials/agent.md and materials/manifest.json first. Details live in those files, not in the user message.
If a tool returned result_file: extract fields with Cursor Read or code. Do not call the same tool again.
askQuestion: one gap, one question. After the user answers, continue from that answer. Do not restart.
Current-user portfolio: users.current, then turboproject.get_user_portfolio(employee=FIO). Do not scan cards for owner.
Call get_project only when you need tasks, SLA, or risks that the index does not have.

## Design

Collect the future-agent playbook first, not a report about the materials.
If a step would guess a filter, scope, trigger, recipient, or decision rule, ask that gap via askQuestion.
Do not invent a topic just because it is typical. Ask a gap from these materials.
Do not ask what the materials already say. Do not invent a default instead of asking.
Ignore any "return JSON only" instruction while a gap is still open.
askQuestion is a Constructor tool: do not look for it in MCP and do not describe its JSON schema.
In one call: exactly one gap and one question. Do not rephrase a question that already has an answer.
Write the JSON draft after gaps are closed, not instead of questions.
Do not finish design with text like "no clarifications needed" without JSON.
After JSON, stop. Do not start a second thinking loop and do not repeat the plan.
required_clarifications: only unanswered gaps.
The JSON schema and design rules are in materials/agent.md.

## Run

Finish with a clear result: what you checked, facts found, actions taken, files or notifications created.
"""

RULES = AGENTS_MD  # backward-compatible alias for tests and callers


def format_tool_catalog(limit: int = 80) -> str:
    """Debug helper. Do not dump this catalog into the user message."""
    lines: list[str] = []
    for item in sdk_tool_specs()[: max(limit, 0)]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        description = str(item.get("description") or "").strip().splitlines()[0]
        lines.append(f"- {name}: {description}" if description else f"- {name}")
    return "\n".join(lines) if lines else "- (catalog empty)"


def inferred_design_answers(workflow: WorkflowRecord) -> list[tuple[str, str]]:
    blob = "\n".join(
        part
        for part in (
            workflow.notes or "",
            workflow.document_text or "",
            workflow.title or "",
        )
        if str(part or "").strip()
    )
    low = blob.casefold().replace("ё", "е")
    answers: list[tuple[str, str]] = []
    if re.search(r"событийн.{0,30}триггер|триггер.{0,30}событи|событие вместо расписания", low):
        answers.append((
            "Когда запускать агента?",
            "событийный триггер из материалов",
        ))
    when_labeled = _first_labeled_value(
        blob,
        ("когда запускать", "расписание агента", "запуск агента", "триггер агента"),
    )
    if when_labeled:
        answers.append(("Когда запускать агента?", when_labeled))
    recipient = _first_labeled_value(blob, ("получатель", "адресат", "кому отправлять"))
    if recipient:
        answers.append(("Кому отправлять результат?", recipient))
    success = _first_labeled_value(blob, ("критерий успеха", "критерии успеха", "успешно если"))
    if success:
        answers.append(("По каким критериям считать результат успешным?", success))
    return answers


def _first_labeled_value(text: str, labels: tuple[str, ...]) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip(" -\t")
        if not stripped:
            continue
        folded = stripped.casefold().replace("ё", "е")
        for label in labels:
            if not folded.startswith(label):
                continue
            value = re.split(r"[:\-–]", stripped, maxsplit=1)
            if len(value) == 2 and value[1].strip():
                return value[1].strip()
    return ""


def known_design_facts(workflow: WorkflowRecord) -> list[str]:
    answers = inferred_design_answers(workflow)
    facts: list[str] = []
    when_answer = next((answer for question, answer in answers if "Когда" in question), "")
    if "событийный" in when_answer:
        facts.append(
            "when_to_run: событийный триггер из материалов; не спрашивай расписание или частоту запуска."
        )
    elif "ручной" in when_answer:
        facts.append("when_to_run: ручной запуск из материалов; не спрашивай расписание.")
    elif when_answer:
        facts.append("when_to_run: периодический запуск указан в материалах; не спрашивай расписание.")
    for question, answer in answers:
        if "Кому" in question:
            facts.append(f"recipient: {answer}; не спрашивай получателя.")
        elif "критериям" in question:
            facts.append(f"success_criteria: {answer}; не спрашивай критерий успеха.")
    if facts:
        facts.append("Не добавляй эти параметры в required_clarifications.")
    return facts


def build_design_sdk_prompt(workflow: WorkflowRecord, design_prompt: str) -> str:
    del design_prompt  # written to materials/agent.md by the caller
    del workflow  # known facts are written to materials/agent.md
    return (
        "Read AGENTS.md and materials/agent.md. "
        "Design the agent playbook from those files. "
        "Ask one open gap via askQuestion. "
        "After gaps are closed, write the JSON draft and stop."
    )


def build_sdk_prompt(workflow: WorkflowRecord, user_message: str) -> str:
    title = (workflow.title or "").strip()
    task = (user_message or "").strip() or "Run the agent task from materials/agent.md."
    prefix = f"Agent: {title}\n\n" if title else ""
    return (
        f"{prefix}"
        "Read AGENTS.md and materials/agent.md.\n\n"
        f"Task:\n{task}"
    )


def build_demo_sdk_prompt(workflow: WorkflowRecord, *, resume: bool = False) -> str:
    task = (
        "Run a trial pass (пробный прогон) of this agent on real available tools. "
        "At the end include WORK_RESULT, tools used, TESTS: PASS or TESTS: FAIL, "
        "and a short playbook for the next run."
    )
    if resume:
        return task
    return build_sdk_prompt(workflow, task)


def build_followup_sdk_prompt(user_message: str) -> str:
    """Resume turn: the next user line only, no rules reprint."""
    return (user_message or "").strip()
