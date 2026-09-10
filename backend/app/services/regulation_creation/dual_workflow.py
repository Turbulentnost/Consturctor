"""Dual-agent regulation interview: document researcher + human interviewer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.workflow import Workflow
from app.services.regulation_creation.interview import (
    _clean_str,
    merge_agent_payload,
    normalize_interview_state,
)
from app.services.regulation_creation.pipeline import (
    COLLECT_REQUIRED_FIELDS,
    _collect_required_gaps_for_process,
    normalize_pipeline,
)

logger = logging.getLogger(__name__)

DUAL_AGENT_STATIC = Path(__file__).resolve().parents[2] / "static" / "regulation_dual_agent"

FUNDAMENTAL_FIELDS = frozenset(
    {"roleStatus", "actor", "workLocation", "frequency", "trigger", "steps", "tool", "periodicity", "triggerAction", "userAction"}
)

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "workLocation": ("workLocation", "tool"),
    "frequency": ("frequency", "periodicity"),
    "trigger": ("trigger", "triggerAction"),
    "steps": ("steps", "userAction"),
}


def dual_workflow_enabled(state: dict[str, Any]) -> bool:
    pipeline = normalize_pipeline(state.get("pipeline") if isinstance(state, dict) else {})
    return bool(pipeline.get("dualWorkflow") or state.get("dualWorkflow"))


def enable_dual_workflow(state: dict[str, Any]) -> dict[str, Any]:
    out = normalize_interview_state(state)
    pipeline = normalize_pipeline(out.get("pipeline"))
    pipeline["dualWorkflow"] = True
    out["dualWorkflow"] = True
    out["pipeline"] = pipeline
    return out


def static_doc_path(name: str) -> Path:
    return DUAL_AGENT_STATIC / name


def load_static_doc(name: str) -> str:
    path = static_doc_path(name)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return ""


def creation_material_review_rules() -> str:
    return (
        "Сейчас этап MATERIAL_REVIEW: изучи materials/* и interview.json.\n"
        "По КАЖДОМУ процессу оцени полноту для регламента (0–100).\n"
        "Не задавай вопросов пользователю. Не пиши document.\n"
        "Верни JSON:\n"
        "{\n"
        '  "status": "need_more",\n'
        '  "message": "Краткий итог обзора материалов",\n'
        '  "materialReview": [\n'
        '    {"processId":"p1","title":"...","completenessScore":70,\n'
        '     "foundInDocument":[{"field":"frequency","quote":"...","value":"..."}],\n'
        '     "missingInDocument":["trigger","steps"],\n'
        '     "notes":"..."}\n'
        "  ],\n"
        '  "pipeline": {"stage":"select","interviewPhase":"select"}\n'
        "}\n"
        f"\n{load_static_doc('RESEARCHER_AGENT.md')}\n"
    )


EXTENDED_REGULATION_FIELDS = ("inputs", "outputs", "controls", "exceptions", "recipients", "objects")

FIELD_LABELS: dict[str, str] = {
    "workLocation": "где выполняется (система/место)",
    "frequency": "периодичность",
    "trigger": "триггер запуска",
    "steps": "пошаговый алгоритм",
    "inputs": "входы процесса",
    "outputs": "результаты/выходы",
    "controls": "контроль и проверки",
    "exceptions": "исключения и эскалация",
    "recipients": "получатели результата",
    "objects": "объекты работы",
    "actor": "исполнитель",
    "roleStatus": "принадлежность должности",
}


def _extended_gaps_for_process(process: dict[str, Any]) -> list[str]:
    facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
    gaps: list[str] = []
    for field in EXTENDED_REGULATION_FIELDS:
        value = facts.get(field)
        if isinstance(value, list):
            if not [item for item in value if _clean_str(item)]:
                gaps.append(field)
        elif not _clean_str(value):
            gaps.append(field)
    steps = facts.get("steps")
    if isinstance(steps, list) and len([s for s in steps if _clean_str(s)]) < 2 and "steps" not in gaps:
        if _clean_str(steps) or (isinstance(steps, list) and any(_clean_str(s) for s in steps)):
            pass  # steps exist but thin — flagged separately
    return gaps


def _smart_gaps_for_process(process_id: str, pipeline: dict[str, Any]) -> list[str]:
    from app.services.regulation_creation.pipeline import SMART_KEYS

    pid = _clean_str(process_id)
    for block in pipeline.get("blocks") or []:
        if not isinstance(block, dict) or _clean_str(block.get("processId")) != pid:
            continue
        smart = block.get("smart") if isinstance(block.get("smart"), dict) else {}
        return [key for key in SMART_KEYS if smart.get(key) in {"missing", "partial", None, ""}]
    return []


def _gap_report_cache_key(state: dict[str, Any]) -> str:
    pipeline = normalize_pipeline(state.get("pipeline"))
    asked = int(pipeline.get("questionsAskedTotal") or 0)
    selected = ",".join(sorted(str(x) for x in (pipeline.get("selectedProcessIds") or [])))
    facts_sig: list[str] = []
    for process in state.get("processes") or []:
        if not isinstance(process, dict):
            continue
        pid = _clean_str(process.get("id"))
        facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
        facts_sig.append(f"{pid}:{len(facts)}:{hash(tuple(sorted(facts.items())))}")
    return f"{asked}|{selected}|{'|'.join(facts_sig)}"


def build_regulation_gap_report(state: dict[str, Any]) -> dict[str, Any]:
    """Analyze what is still missing for an executable STO regulation."""
    interview = normalize_interview_state(state)
    pipeline = normalize_pipeline(interview.get("pipeline"))
    selected = {
        str(item).strip()
        for item in (pipeline.get("selectedProcessIds") or [])
        if str(item).strip()
    }
    completeness_map = interview.get("processCompleteness")
    if not isinstance(completeness_map, dict):
        completeness_map = {}
    research_queue = interview.get("researchQueue") if isinstance(interview.get("researchQueue"), list) else []
    processes_out: list[dict[str, Any]] = []
    total_gaps = 0
    for raw in interview.get("processes") or []:
        if not isinstance(raw, dict):
            continue
        pid = _clean_str(raw.get("id") or raw.get("processId"))
        if selected and pid not in selected:
            continue
        collect_gaps = _collect_required_gaps_for_process(raw)
        extended_gaps = _extended_gaps_for_process(raw)
        smart_gaps = _smart_gaps_for_process(pid, pipeline)
        review = completeness_map.get(pid) if isinstance(completeness_map.get(pid), dict) else {}
        doc_missing = review.get("missingInDocument") if isinstance(review.get("missingInDocument"), list) else []
        hypotheses = [
            {
                "field": _canonical_field(item.get("field")),
                "hypothesis": _clean_str(item.get("hypothesis")),
                "needsHumanConfirm": bool(item.get("needsHumanConfirm")),
            }
            for item in research_queue
            if isinstance(item, dict) and _clean_str(item.get("processId")) == pid
        ]
        gap_count = len(collect_gaps) + len(extended_gaps) + len(smart_gaps)
        total_gaps += gap_count
        processes_out.append(
            {
                "processId": pid,
                "title": _clean_str(raw.get("title")) or pid,
                "completenessScore": int(review.get("completenessScore") or process_completeness_score(raw)),
                "collectGaps": [FIELD_LABELS.get(g, g) for g in collect_gaps],
                "extendedGaps": [FIELD_LABELS.get(g, g) for g in extended_gaps],
                "smartGaps": smart_gaps,
                "missingInDocument": [str(x) for x in doc_missing],
                "researchHypotheses": hypotheses,
                "knownFacts": _facts_for_process(raw),
            }
        )
    section_risks: list[str] = []
    if any(not p.get("knownFacts", {}).get("steps") for p in processes_out):
        section_risks.append("Раздел 6 «Организация работы» будет без исполняемых алгоритмов")
    if any(p.get("extendedGaps") for p in processes_out):
        section_risks.append("Не хватает входов/выходов/контролей — регламент не применим на практике")
    if total_gaps == 0 and any(p.get("smartGaps") for p in processes_out):
        section_risks.append("SMART-критерии не закрыты — процесс описан расплывчато")
    summary = (
        f"Выбрано процессов: {len(processes_out)}. Открытых пробелов: {total_gaps}. "
        "Сформируй вопросы только по незакрытым полям — не повторяй knownFacts."
    )
    return {
        "summary": summary,
        "sectionRisks": section_risks,
        "processes": processes_out,
    }


def format_gap_report_for_prompt(state: dict[str, Any]) -> str:
    key = _gap_report_cache_key(state)
    cached = state.get("_regulationGapReportCache")
    if isinstance(cached, dict) and cached.get("key") == key:
        text = cached.get("text")
        if isinstance(text, str) and text:
            return text
    report = build_regulation_gap_report(state)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    state["_regulationGapReportCache"] = {"key": key, "text": text, "report": report}
    return text


def creation_researcher_rules() -> str:
    return (
        "Режим RESEARCH: читай materials/*, не задавай вопросов пользователю.\n"
        "Пополняй researchFacts и researchQueue. Ответ строго JSON.\n"
        f"\n{load_static_doc('RESEARCHER_AGENT.md')}\n"
        f"\n{load_static_doc('REGULATION_BRIEF.md')}\n"
    )


def creation_interviewer_dual_rules(*, force_create: bool = False) -> str:
    force = "Можно status=ready и document." if force_create else "Не ready, пока gaps не закрыты."
    return (
        "Режим INTERVIEWER: один вопрос в message, batch roundQuestions для prefetch.\n"
        "Перед каждым ходом изучи regulationGapReport в промпте: что не хватает регламенту для "
        "полноценной работы (алгоритм, триггер, контроль, исключения, ответственность).\n"
        "Не задавай шаблонные вопросы по уже закрытым полям. Если steps есть, но короткие — "
        "уточни детали шагов, системы, сроки, эскалацию.\n"
        f"{force}\n"
        f"\n{load_static_doc('INTERVIEWER_AGENT.md')}\n"
        f"\n{load_static_doc('REGULATION_BRIEF.md')}\n"
    )


def build_research_prefetch_prompt(*, state: dict[str, Any], pipeline: dict[str, Any]) -> str:
    interview = normalize_interview_state(state)
    selected = pipeline.get("selectedProcessIds") or []
    report = build_regulation_gap_report(interview)
    gaps_short = json.dumps(
        [
            {
                "processId": item.get("processId"),
                "title": item.get("title"),
                "collectGaps": item.get("collectGaps"),
                "extendedGaps": item.get("extendedGaps"),
            }
            for item in (report.get("processes") or [])
            if isinstance(item, dict)
        ],
        ensure_ascii=False,
    )
    return (
        "Продолжай исследование materials/*.txt (не перечитывай interview.json целиком).\n"
        f"selectedProcessIds={json.dumps(selected, ensure_ascii=False)}\n"
        f"Пробелы: {report.get('summary')}\n"
        f"gaps={gaps_short}\n"
        "Верни JSON: researchFacts + researchQueue (needsHumanConfirm для спорных полей).\n"
    )


def build_material_review_prompt(*, state: dict[str, Any]) -> str:
    return (
        "Проведи material_review: отчёт о полноте каждого процесса из interview.json.\n"
        "Прочитай все materials/*.txt. Ответ — JSON materialReview.\n"
    )


def completeness_report_markdown(reviews: list[dict[str, Any]]) -> str:
    lines = ["# Отчёт о полноте процессов", ""]
    for item in reviews:
        if not isinstance(item, dict):
            continue
        pid = _clean_str(item.get("processId"))
        title = _clean_str(item.get("title")) or pid
        score = int(item.get("completenessScore") or 0)
        missing = item.get("missingInDocument") or []
        found = item.get("foundInDocument") or []
        notes = _clean_str(item.get("notes"))
        lines.append(f"## {title} ({pid}) — {score}%")
        if found:
            lines.append("### Найдено в документе")
            for row in found:
                if not isinstance(row, dict):
                    continue
                lines.append(f"- **{row.get('field')}**: {row.get('value')} — «{row.get('quote')}»")
        if missing:
            lines.append("### Не хватает")
            lines.append(", ".join(str(x) for x in missing))
        if notes:
            lines.append(f"### Заметки\n{notes}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def apply_material_review(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    out = merge_agent_payload(state, payload)
    reviews = payload.get("materialReview")
    if isinstance(reviews, list):
        out["materialReview"] = reviews
        out["processCompleteness"] = {
            str(item.get("processId") or ""): item
            for item in reviews
            if isinstance(item, dict) and _clean_str(item.get("processId"))
        }
    pipeline = payload.get("pipeline") if isinstance(payload.get("pipeline"), dict) else {}
    stage = _clean_str(pipeline.get("stage")).lower()
    if stage == "select":
        pipe = normalize_pipeline(out.get("pipeline"))
        pipe["stage"] = "select"
        pipe["interviewPhase"] = "select"
        out["pipeline"] = pipe
    return out


def _canonical_field(field: str) -> str:
    text = _clean_str(field)
    for canonical, aliases in FIELD_ALIASES.items():
        if text in aliases or text == canonical:
            return canonical
    return text


def _facts_for_process(process: dict[str, Any]) -> dict[str, str]:
    facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
    out: dict[str, str] = {}
    for key in ("workLocation", "frequency", "trigger", "steps", "actor"):
        val = _clean_str(facts.get(key) or process.get(key))
        if val:
            out[key] = val
    for canonical, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            val = _clean_str(facts.get(alias) or process.get(alias))
            if val and canonical not in out:
                out[canonical] = val
    role = _clean_str(process.get("roleStatus"))
    if role:
        out["roleStatus"] = role
    return out


def merge_field_value(
    *,
    field: str,
    human_value: str,
    research_value: str,
    research_confidence: str = "",
) -> tuple[str, str]:
    """Return (value, source). Human wins on fundamental conflict."""
    field = _canonical_field(field)
    human = _clean_str(human_value)
    research = _clean_str(research_value)
    conf = _clean_str(research_confidence).lower()
    if human and research and human.casefold() != research.casefold():
        if field in FUNDAMENTAL_FIELDS or _canonical_field(field) in {
            "workLocation",
            "frequency",
            "trigger",
            "steps",
            "roleStatus",
            "actor",
        }:
            return human, "human"
        if conf == "high" and not human:
            return research, "research"
        return human or research, "human" if human else "research"
    if human:
        return human, "human"
    if research and conf in {"high", "medium", ""}:
        return research, "research"
    return research, "research"


def apply_research_payload(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    out = normalize_interview_state(state)
    research_facts = payload.get("researchFacts")
    if not isinstance(research_facts, list):
        return out
    by_process: dict[str, dict[str, Any]] = {}
    for raw in out.get("processes") or []:
        if isinstance(raw, dict):
            pid = _clean_str(raw.get("id") or raw.get("processId"))
            if pid:
                by_process[pid] = raw
    stored = out.get("researchFacts") if isinstance(out.get("researchFacts"), dict) else {}
    for item in research_facts:
        if not isinstance(item, dict):
            continue
        pid = _clean_str(item.get("processId"))
        field = _canonical_field(item.get("field"))
        value = _clean_str(item.get("value"))
        if not pid or not field or not value:
            continue
        conf = _clean_str(item.get("confidence")).lower() or "medium"
        if conf == "low":
            continue
        process = by_process.get(pid)
        if process is None:
            continue
        known = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
        current_human = ""
        for alias in (field, *FIELD_ALIASES.get(field, ())):
            current_human = _clean_str(known.get(alias) or process.get(alias))
            if current_human:
                break
        merged, source = merge_field_value(
            field=field,
            human_value=current_human,
            research_value=value,
            research_confidence=conf,
        )
        known[field if field in known or field not in FIELD_ALIASES else field] = merged
        if field == "workLocation":
            known["workLocation"] = merged
        elif field == "frequency":
            known["frequency"] = merged
        elif field == "trigger":
            known["trigger"] = merged
        elif field == "steps":
            known["steps"] = merged
        else:
            known[field] = merged
        process["knownFacts"] = known
        stored[f"{pid}:{field}"] = {
            "value": merged,
            "source": source,
            "confidence": conf,
            "quote": _clean_str(item.get("sourceQuote")),
        }
    out["researchFacts"] = stored
    queue = payload.get("researchQueue")
    if isinstance(queue, list):
        out["researchQueue"] = queue[-40:]
    from app.services.regulation_creation.question_queue import enqueue_research_hypotheses

    return enqueue_research_hypotheses(out)


def process_completeness_score(process: dict[str, Any]) -> int:
    gaps = _collect_required_gaps_for_process(process)
    total = len(COLLECT_REQUIRED_FIELDS)
    if total <= 0:
        return 100
    filled = total - len(gaps)
    role = _clean_str(process.get("roleStatus"))
    if role != "belongs":
        filled = max(0, filled - 1)
    return max(0, min(100, int(round(filled / total * 100))))


def processes_ready_for_agent(state: dict[str, Any]) -> list[dict[str, Any]]:
    interview = normalize_interview_state(state)
    pipeline = normalize_pipeline(interview.get("pipeline"))
    selected = {str(x).strip() for x in (pipeline.get("selectedProcessIds") or []) if str(x).strip()}
    spawned = {
        str(x.get("processId") or "")
        for x in (interview.get("spawnedAgents") or [])
        if isinstance(x, dict)
    }
    ready: list[dict[str, Any]] = []
    for process in interview.get("processes") or []:
        if not isinstance(process, dict):
            continue
        pid = _clean_str(process.get("id") or process.get("processId"))
        if selected and pid not in selected:
            continue
        if pid in spawned:
            continue
        if _clean_str(process.get("roleStatus")) != "belongs":
            continue
        if _collect_required_gaps_for_process(process):
            continue
        title = _clean_str(process.get("title")) or pid
        ready.append(
            {
                "processId": pid,
                "title": title,
                "ready": True,
                "agentTitle": title,
                "completenessScore": process_completeness_score(process),
            }
        )
    return ready


def _process_agent_notes(process: dict[str, Any], regulation_title: str = "") -> str:
    title = _clean_str(process.get("title"))
    facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
    lines = [
        f"ИИ-агент для процесса «{title}» из регламента «{regulation_title or 'должности'}».",
        "",
        f"Исполнитель: {_clean_str(process.get('actor'))}",
        f"Где выполняется: {_clean_str(facts.get('workLocation') or process.get('tool'))}",
        f"Периодичность: {_clean_str(facts.get('frequency') or process.get('periodicity'))}",
        f"Триггер: {_clean_str(facts.get('trigger') or process.get('triggerAction'))}",
        f"Шаги: {_clean_str(facts.get('steps') or process.get('userAction'))}",
        "",
        "Повторяй этот процесс по собранным фактам. Не расширяй объём без запроса пользователя.",
    ]
    return "\n".join(line for line in lines if line).strip()


def spawn_regulation_process_agents(
    db: Session,
    *,
    user_id: str,
    interview: dict[str, Any],
    regulation_title: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create published workflow agents for processes that are ready."""
    from app.services.workflows.service import _local_playbook

    ready = processes_ready_for_agent(interview)
    if not ready:
        return [], normalize_interview_state(interview)
    state = normalize_interview_state(interview)
    spawned_list = list(state.get("spawnedAgents") or [])
    spawned_ids = {str(x.get("processId") or "") for x in spawned_list if isinstance(x, dict)}
    processes_by_id = {
        _clean_str(p.get("id") or p.get("processId")): p
        for p in (state.get("processes") or [])
        if isinstance(p, dict)
    }
    created: list[dict[str, Any]] = []
    for item in ready:
        pid = _clean_str(item.get("processId"))
        if not pid or pid in spawned_ids:
            continue
        process = processes_by_id.get(pid) or {}
        agent_title = _clean_str(item.get("agentTitle")) or _clean_str(process.get("title")) or pid
        notes = _process_agent_notes(process, regulation_title)
        workflow_id = str(uuid4())
        playbook = _local_playbook(
            title=agent_title,
            demo_text=notes,
            tools=["desktop.report.export"],
            answered_scope=agent_title,
        )
        row = Workflow(
            id=workflow_id,
            user_id=user_id,
            title=agent_title,
            phase="done",
            notes=notes,
            document_name=f"{agent_title}.md",
            document_text=notes,
            plan_json={"goal": agent_title, "title": agent_title, "steps": []},
            attachments_meta=[],
            local_run={
                "status": "published",
                "published": True,
                "can_publish": False,
                "tests_status": "pass",
                "demo_ok": True,
                "runtime": "mcp",
                "ui_mode": "chat",
                "playbook": playbook,
                "source": "regulation_creation",
                "regulationProcessId": pid,
            },
        )
        db.add(row)
        entry = {
            "processId": pid,
            "workflowId": workflow_id,
            "title": agent_title,
            "published": True,
        }
        spawned_list.append(entry)
        created.append(entry)
        spawned_ids.add(pid)
        logger.info("reg_create spawned agent workflow=%s process=%s title=%s", workflow_id, pid, agent_title)
    state["spawnedAgents"] = spawned_list
    return created, state

def merge_agent_candidates_from_payload(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    candidates = payload.get("processAgentCandidates")
    if isinstance(candidates, list):
        state["processAgentCandidates"] = candidates
    return state
