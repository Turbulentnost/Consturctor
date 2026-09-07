"""Block-based regulation creation pipeline: stages, rounds, SMART, material slices."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

PIPELINE_STAGES = ("upload", "extract", "select", "interview", "assemble", "done")
SMART_KEYS = ("S", "M", "A", "R", "T")
SMART_STATUSES = ("missing", "partial", "done")
ROUND_STATUSES = ("open", "answered", "reviewed")
BLOCK_STATUSES = ("pending", "active", "done")

MAX_QUESTIONS_PER_ROUND = 50
MIN_ROUNDS = 3
MAX_QUESTIONS_TOTAL = 250

_CONCRETE_MARKERS = (
    "outlook",
    "почт",
    "1с",
    "1c",
    "excel",
    "word",
    "telegram",
    "teams",
    "файл",
    "реестр",
    "карточ",
    "созда",
    "отправ",
    "заполн",
)
_TIME_MARKERS = (
    r"\d+\s*(?:мин|час|ч\.|дн|день|дней|раб)",
    r"ежеднев",
    r"еженедел",
    r"ежемесяч",
    r"по\s+расписан",
    r"не\s+позднее",
    r"до\s+\d",
)
_MEASURABLE_MARKERS = (
    "kpi",
    "%",
    "критер",
    "провер",
    "контроль",
    "показател",
    "срок",
    "не позднее",
)


def default_pipeline() -> dict[str, Any]:
    return {
        "stage": "upload",
        "round": 0,
        "maxQuestionsPerRound": MAX_QUESTIONS_PER_ROUND,
        "minRounds": MIN_ROUNDS,
        "maxQuestionsTotal": MAX_QUESTIONS_TOTAL,
        "questionsAskedTotal": 0,
        "selectedProcessIds": [],
        "blocks": [],
        "rounds": [],
        "questionnaire": {},
        "roundQuestions": [],
        "progress": 0,
    }


def normalize_pipeline(raw: Any) -> dict[str, Any]:
    base = default_pipeline()
    if not isinstance(raw, dict):
        return base
    out = {**base, **raw}
    stage = str(out.get("stage") or "upload").strip().lower()
    out["stage"] = stage if stage in PIPELINE_STAGES else "upload"
    out["round"] = max(0, int(out.get("round") or 0))
    out["maxQuestionsPerRound"] = MAX_QUESTIONS_PER_ROUND
    out["minRounds"] = MIN_ROUNDS
    out["maxQuestionsTotal"] = MAX_QUESTIONS_TOTAL
    out["questionsAskedTotal"] = max(0, int(out.get("questionsAskedTotal") or 0))
    selected = out.get("selectedProcessIds")
    out["selectedProcessIds"] = (
        [str(item).strip() for item in selected if str(item).strip()]
        if isinstance(selected, list)
        else []
    )
    out["blocks"] = _normalize_blocks(out.get("blocks"))
    out["rounds"] = _normalize_rounds(out.get("rounds"))
    quest = out.get("questionnaire")
    out["questionnaire"] = quest if isinstance(quest, dict) else {}
    rq = out.get("roundQuestions")
    out["roundQuestions"] = _normalize_round_questions(rq if isinstance(rq, list) else [])
    out["progress"] = _compute_progress(out)
    return out


def pipeline_snapshot(state: Any) -> dict[str, Any]:
    interview = state if isinstance(state, dict) else {}
    return normalize_pipeline(interview.get("pipeline"))


def set_pipeline_stage(state: dict[str, Any], stage: str) -> dict[str, Any]:
    out = deepcopy(state) if isinstance(state, dict) else {}
    pipeline = normalize_pipeline(out.get("pipeline"))
    if stage in PIPELINE_STAGES:
        pipeline["stage"] = stage
    pipeline["progress"] = _compute_progress(pipeline)
    out["pipeline"] = pipeline
    return out


def mark_upload_received(state: dict[str, Any]) -> dict[str, Any]:
    """After first attachment lands, move upload → extract."""
    out = deepcopy(state) if isinstance(state, dict) else {}
    pipeline = normalize_pipeline(out.get("pipeline"))
    attachments = out.get("attachments") if isinstance(out.get("attachments"), list) else []
    if attachments and pipeline["stage"] == "upload":
        pipeline["stage"] = "extract"
    pipeline["progress"] = _compute_progress(pipeline)
    out["pipeline"] = pipeline
    return out


def merge_pipeline_payload(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Merge extract / roundQuestions / blocks from agent JSON into interview state."""
    out = deepcopy(state) if isinstance(state, dict) else {}
    pipeline = normalize_pipeline(out.get("pipeline"))
    has_selection = bool(pipeline.get("selectedProcessIds"))
    incoming = payload.get("pipeline") if isinstance(payload.get("pipeline"), dict) else {}
    if incoming:
        if isinstance(incoming.get("blocks"), list) and incoming["blocks"]:
            pipeline["blocks"] = _normalize_blocks(incoming["blocks"])
        if isinstance(incoming.get("questionnaire"), dict):
            pipeline["questionnaire"] = {**pipeline["questionnaire"], **incoming["questionnaire"]}
        stage = str(incoming.get("stage") or "").strip().lower()
        if stage in PIPELINE_STAGES and _stage_rank(stage) >= _stage_rank(pipeline["stage"]):
            # Never skip select → interview without explicit user process selection.
            if not (stage in ("interview", "assemble", "done") and not has_selection):
                pipeline["stage"] = stage

    blocks_from_processes = blocks_from_processes_list(out.get("processes") or [])
    if blocks_from_processes and not pipeline["blocks"]:
        pipeline["blocks"] = blocks_from_processes
    elif blocks_from_processes:
        pipeline["blocks"] = _merge_blocks(pipeline["blocks"], blocks_from_processes)

    # Round questions only after the user confirmed processes on the select step.
    round_questions = payload.get("roundQuestions")
    if not isinstance(round_questions, list):
        interview = payload.get("interview") if isinstance(payload.get("interview"), dict) else {}
        round_questions = interview.get("roundQuestions") if isinstance(interview, dict) else None
    if isinstance(round_questions, list) and round_questions and has_selection:
        pipeline = start_round(pipeline, round_questions)

    processes = out.get("processes") if isinstance(out.get("processes"), list) else []
    has_process_candidates = bool(pipeline["blocks"]) or bool(processes)
    if not has_selection and has_process_candidates and pipeline["stage"] in ("upload", "extract", "interview"):
        pipeline["stage"] = "select"
    elif pipeline["stage"] == "extract" and pipeline["blocks"]:
        pipeline["stage"] = "select"

    # Refresh SMART from current process facts.
    pipeline["blocks"] = [
        {**block, "smart": smart_check_block(block, out)} for block in pipeline["blocks"]
    ]
    pipeline["progress"] = _compute_progress(pipeline)
    out["pipeline"] = pipeline
    return out


def blocks_from_processes_list(processes: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, raw in enumerate(processes, start=1):
        if not isinstance(raw, dict):
            continue
        process_id = _clean(raw.get("id") or raw.get("processId")) or f"p{index}"
        title = _clean(raw.get("title")) or process_id
        facts = raw.get("knownFacts") if isinstance(raw.get("knownFacts"), dict) else {}
        elements = {
            "inputs": _as_list(facts.get("inputs")),
            "trigger": _as_list(facts.get("trigger")),
            "steps": _as_list(facts.get("steps")),
            "outputs": _as_list(facts.get("outputs")),
            "controls": _as_list(facts.get("controls")),
            "workLocation": _as_list(facts.get("workLocation")),
            "frequency": _as_list(facts.get("frequency")),
            "recipients": _as_list(facts.get("recipients")),
            "exceptions": _as_list(facts.get("exceptions")),
        }
        block = {
            "id": f"b-{process_id}",
            "processId": process_id,
            "title": title,
            "sourceRefs": raw.get("sourceRefs") if isinstance(raw.get("sourceRefs"), list) else [],
            "elements": elements,
            "smart": {key: "missing" for key in SMART_KEYS},
            "status": "pending",
        }
        block["smart"] = smart_check_block(block, {"processes": processes})
        out.append(block)
    return out


def select_processes(state: dict[str, Any], process_ids: list[str]) -> dict[str, Any]:
    """Mark selected processes as belongs, others foreign; enter interview stage."""
    out = deepcopy(state) if isinstance(state, dict) else {}
    selected = [str(item).strip() for item in process_ids if str(item).strip()]
    if not selected:
        raise ValueError("Нужно выбрать хотя бы один процесс")
    selected_set = set(selected)
    for key in ("processes", "functions"):
        items = out.get(key) if isinstance(out.get(key), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            pid = _clean(item.get("id") or item.get("processId") or item.get("functionId"))
            item["roleStatus"] = "belongs" if pid in selected_set else "foreign"
    pipeline = normalize_pipeline(out.get("pipeline"))
    pipeline["selectedProcessIds"] = selected
    if not pipeline["blocks"]:
        pipeline["blocks"] = blocks_from_processes_list(out.get("processes") or [])
    for block in pipeline["blocks"]:
        pid = _clean(block.get("processId"))
        if pid in selected_set:
            block["status"] = "active" if block.get("status") == "pending" else block.get("status") or "active"
            block["smart"] = smart_check_block(block, out)
        else:
            block["status"] = "pending"
    pipeline["stage"] = "interview"
    if pipeline["round"] <= 0:
        pipeline["round"] = 0
    pipeline["progress"] = _compute_progress(pipeline)
    out["pipeline"] = pipeline
    return out


def start_round(pipeline: dict[str, Any], questions: list[Any]) -> dict[str, Any]:
    pipe = normalize_pipeline(pipeline)
    remaining = pipe["maxQuestionsTotal"] - pipe["questionsAskedTotal"]
    if remaining <= 0:
        pipe["stage"] = "assemble"
        pipe["progress"] = _compute_progress(pipe)
        return pipe
    normalized = _normalize_round_questions(questions)[: min(pipe["maxQuestionsPerRound"], remaining)]
    if not normalized:
        return pipe
    next_round = pipe["round"] + 1
    # Close previous open round as reviewed if still open.
    for item in pipe["rounds"]:
        if item.get("status") == "open":
            item["status"] = "reviewed"
    pipe["round"] = next_round
    pipe["roundQuestions"] = normalized
    pipe["rounds"].append(
        {
            "index": next_round,
            "questionIds": [q["id"] for q in normalized],
            "status": "open",
        }
    )
    pipe["questionsAskedTotal"] = pipe["questionsAskedTotal"] + len(normalized)
    pipe["stage"] = "interview"
    pipe["progress"] = _compute_progress(pipe)
    return pipe


def apply_round_answers(
    state: dict[str, Any],
    answers: list[dict[str, Any]] | None = None,
    *,
    free_message: str = "",
) -> dict[str, Any]:
    """Apply structured round answers and/or a free-form chat message."""
    out = deepcopy(state) if isinstance(state, dict) else {}
    pipeline = normalize_pipeline(out.get("pipeline"))
    answer_list = answers if isinstance(answers, list) else []
    stored_answers = out.get("answers") if isinstance(out.get("answers"), list) else []
    questionnaire = dict(pipeline.get("questionnaire") or {})

    for raw in answer_list:
        if not isinstance(raw, dict):
            continue
        qid = _clean(raw.get("questionId") or raw.get("id"))
        text = _clean(raw.get("answer") or raw.get("text") or raw.get("value"))
        if not qid and not text:
            continue
        entry = {
            "questionId": qid,
            "answer": text,
            "processId": _clean(raw.get("processId") or raw.get("functionId")),
            "field": _clean(raw.get("field")),
            "source": "round",
        }
        stored_answers.append(entry)
        if qid:
            questionnaire[qid] = text
        # Patch matching open round question.
        for q in pipeline["roundQuestions"]:
            if q.get("id") == qid:
                q["answer"] = text
                q["status"] = "answered"
        _apply_answer_to_facts(out, entry)

    if free_message.strip():
        stored_answers.append(
            {
                "questionId": "",
                "answer": free_message.strip(),
                "processId": "",
                "field": "",
                "source": "user_free",
            }
        )

    out["answers"] = stored_answers[-500:]
    if answer_list:
        for rnd in pipeline["rounds"]:
            if rnd.get("index") == pipeline["round"] and rnd.get("status") == "open":
                rnd["status"] = "answered"
        if not any(not _clean(q.get("answer")) for q in pipeline["roundQuestions"]):
            pipeline["roundQuestions"] = []

    selected = set(pipeline["selectedProcessIds"])
    base_blocks = blocks_from_processes_list(out.get("processes") or [])
    merged_blocks = _merge_blocks(pipeline["blocks"], base_blocks)
    for block in merged_blocks:
        smart = smart_check_block(block, out)
        block["smart"] = smart
        if selected and _clean(block.get("processId")) not in selected:
            block["status"] = "pending"
        else:
            block["status"] = _block_status_from_smart(smart, block)
    pipeline["blocks"] = merged_blocks
    pipeline["questionnaire"] = questionnaire
    pipeline["progress"] = _compute_progress(pipeline)
    out["pipeline"] = pipeline
    return out


def round_gate(*, pipeline: dict[str, Any], force_create: bool = False) -> str | None:
    """Return blocker message if ready is not allowed yet, else None."""
    pipe = normalize_pipeline(pipeline)
    if force_create:
        return None
    # Legacy sessions (no rounds started / no process selection) keep old ready rules.
    if pipe["round"] <= 0 and not pipe["rounds"] and not pipe["selectedProcessIds"]:
        return None
    if pipe["round"] < pipe["minRounds"]:
        return (
            f"Нужно пройти минимум {pipe['minRounds']} раунда опроса "
            f"(сейчас раунд {pipe['round']}). Продолжаем уточнение."
        )
    if pipe["questionsAskedTotal"] >= pipe["maxQuestionsTotal"]:
        return None  # cap reached — allow assemble
    # Still have critical SMART missing on selected blocks?
    selected = set(pipe["selectedProcessIds"])
    for block in pipe["blocks"]:
        if selected and _clean(block.get("processId")) not in selected:
            continue
        smart = block.get("smart") if isinstance(block.get("smart"), dict) else {}
        if any(smart.get(key) == "missing" for key in SMART_KEYS):
            return (
                "По выбранным процессам ещё не закрыты SMART-критерии. "
                "Нужен следующий раунд уточняющих вопросов."
            )
    return None


def can_start_next_round(pipeline: dict[str, Any]) -> bool:
    pipe = normalize_pipeline(pipeline)
    return pipe["questionsAskedTotal"] < pipe["maxQuestionsTotal"]


def should_assemble(pipeline: dict[str, Any], *, force_create: bool = False) -> bool:
    pipe = normalize_pipeline(pipeline)
    if force_create:
        return True
    if pipe["questionsAskedTotal"] >= pipe["maxQuestionsTotal"] and pipe["round"] >= pipe["minRounds"]:
        return True
    if pipe["round"] < pipe["minRounds"]:
        return False
    gate = round_gate(pipeline=pipe, force_create=False)
    return gate is None


def smart_check_block(block: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, str]:
    elements = block.get("elements") if isinstance(block.get("elements"), dict) else {}
    process = _process_for_block(block, state)
    facts = process.get("knownFacts") if isinstance(process, dict) and isinstance(process.get("knownFacts"), dict) else {}
    steps = _text_join(elements.get("steps"), facts.get("steps"), process.get("userAction") if process else "")
    trigger = _text_join(elements.get("trigger"), facts.get("trigger"), process.get("triggerAction") if process else "")
    controls = _text_join(elements.get("controls"), facts.get("controls"))
    tool = _text_join(elements.get("workLocation"), facts.get("workLocation"), process.get("tool") if process else "")
    frequency = _text_join(elements.get("frequency"), facts.get("frequency"), process.get("periodicity") if process else "")
    actor = _clean((process or {}).get("actor")) if process else ""
    role = _clean((process or {}).get("roleStatus") or block.get("roleStatus"))

    return {
        "S": _smart_level(steps, concrete=True),
        "M": _smart_level(controls, measurable=True),
        "A": _smart_level(tool, concrete=True),
        "R": "done" if role == "belongs" or (actor and role != "foreign") else ("partial" if actor else "missing"),
        "T": _smart_level(_text_join(trigger, frequency), timed=True),
    }


def slice_materials_for_prompt(state: dict[str, Any], *, full: bool = False) -> list[dict[str, Any]]:
    """Return attachment payloads for prompt/workspace: full text or per-process slices."""
    interview = state if isinstance(state, dict) else {}
    attachments = [item for item in (interview.get("attachments") or []) if isinstance(item, dict)]
    pipeline = normalize_pipeline(interview.get("pipeline"))
    if full or pipeline["stage"] in ("upload", "extract", "assemble", "done"):
        return attachments

    selected = set(pipeline["selectedProcessIds"])
    processes = [p for p in (interview.get("processes") or []) if isinstance(p, dict)]
    if selected:
        processes = [p for p in processes if _clean(p.get("id")) in selected]
    if not processes:
        return attachments

    slices: list[dict[str, Any]] = []
    # Short global context: first 2k of each attachment.
    for att in attachments:
        name = Path(str(att.get("name") or "file")).name
        text = str(att.get("text") or "")
        slices.append(
            {
                "id": f"{att.get('id') or name}-global",
                "name": f"global-{name}",
                "kind": att.get("kind") or "text",
                "text": text[:2000] + ("\n...[global context truncated]" if len(text) > 2000 else ""),
            }
        )
    for process in processes:
        pid = _clean(process.get("id")) or "process"
        refs = process.get("sourceRefs") if isinstance(process.get("sourceRefs"), list) else []
        chunks: list[str] = [f"# Process {pid}: {_clean(process.get('title'))}"]
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            quote = _clean(ref.get("quote"))
            file_name = _clean(ref.get("file"))
            if quote:
                chunks.append(f"## from {file_name or 'source'}\n{quote}")
            elif file_name:
                for att in attachments:
                    if Path(str(att.get("name") or "")).name == Path(file_name).name:
                        text = str(att.get("text") or "")
                        chunks.append(text[:8000])
                        break
        if len(chunks) == 1:
            # Fallback: keyword window from first attachment.
            title = _clean(process.get("title"))
            for att in attachments:
                text = str(att.get("text") or "")
                window = _keyword_window(text, title) if title else text[:6000]
                if window:
                    chunks.append(window)
                    break
        slices.append(
            {
                "id": f"process-{pid}",
                "name": f"{pid}.txt",
                "kind": "text",
                "text": "\n\n".join(chunks),
            }
        )
    return slices


def creation_extract_rules() -> str:
    return (
        "Сейчас этап EXTRACT: только выдели процессы и мини-блоки из материалов.\n"
        "Не задавай вопросы пользователю. Не пиши document. Не возвращай roundQuestions.\n"
        "После извлечения stage должен быть select — пользователь сам отметит процессы.\n"
        "Верни JSON:\n"
        "{\n"
        '  "status": "need_more",\n'
        '  "message": "Кратко: нашёл N процессов. Отметьте, какие относятся к вашей должности.",\n'
        '  "interview": {\n'
        '    "processes": [{"id":"p1","title":"...","actor":"...","roleStatus":"unclear",'
        '"knownFacts":{},"unknowns":[],"sourceRefs":[{"file":"...","quote":"..."}]}],\n'
        '    "functions": []\n'
        "  },\n"
        '  "pipeline": {"stage":"select","blocks":[{"id":"b-p1","processId":"p1","title":"...",'
        '"sourceRefs":[],"elements":{"inputs":[],"trigger":[],"steps":[],"outputs":[],'
        '"controls":[],"workLocation":[],"frequency":[]},"smart":{"S":"missing","M":"missing",'
        '"A":"missing","R":"missing","T":"missing"},"status":"pending"}]},\n'
        '  "roundQuestions": [],\n'
        '  "document": {}\n'
        "}\n"
        "sourceRefs обязательны: короткие цитаты из файла.\n"
    )


def creation_select_rules() -> str:
    return (
        "Сейчас этап SELECT: пользователь выбирает процессы для агента.\n"
        "Не задавай вопросы. Не возвращай roundQuestions. Не пиши document.\n"
        "Кратко подтверди список процессов и попроси отметить нужные.\n"
        "Верни JSON:\n"
        "{\n"
        '  "status": "need_more",\n'
        '  "message": "Отметьте процессы вашей должности — после выбора начну опрос по SMART.",\n'
        '  "roundQuestions": [],\n'
        '  "document": {}\n'
        "}\n"
    )


def creation_round_interview_rules(*, force_create: bool = False) -> str:
    force = (
        "Пользователь запросил принудительное создание: можно перейти к document."
        if force_create
        else (
            f"Не возвращай status='ready', пока не завершено минимум {MIN_ROUNDS} раунда "
            f"и SMART по выбранным процессам не закрыт (или пока не достигнут лимит "
            f"{MAX_QUESTIONS_TOTAL} вопросов)."
        )
    )
    return (
        "Ты ведёшь блочное интервью для регламента раундами.\n"
        f"За один ход верни batch roundQuestions (максимум {MAX_QUESTIONS_PER_ROUND} вопросов).\n"
        "Сначала просмотри уже данные answers и questionnaire в interview.json — не повторяй закрытое.\n"
        "Выделяй мини-функциональные блоки и спрашивай только недостающие элементы (SMART).\n"
        "Человек может параллельно писать свободные сообщения — учитывай их как факты.\n"
        "message — краткое введение к раунду (1–3 предложения).\n"
        f"{force}\n"
        "Ответ строго JSON без markdown:\n"
        "{\n"
        '  "status": "need_more|ready",\n'
        '  "message": "кратко о раунде",\n'
        '  "quickAnswers": [],\n'
        '  "roundQuestions": [{"id":"q1","processId":"p1","field":"trigger|steps|controls|tool|frequency|roleStatus",'
        '"text":"...","smartKey":"S|M|A|R|T","options":["..."]}],\n'
        '  "interview": {"processes":[],"functions":[]},\n'
        '  "pipeline": {"blocks":[]},\n'
        '  "document": {}\n'
        "}\n"
        "document заполняй только при status='ready'.\n"
    )


def incremental_document_from_state(state: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build/refresh draft document JSON from interview facts (gradual fill)."""
    from app.services.regulation_creation.interview import document_from_interview

    title = ""
    if isinstance(previous, dict):
        title = str(previous.get("title") or "").strip()
    document = document_from_interview(state, title)
    if isinstance(previous, dict) and previous.get("sections"):
        # Prefer newer paragraphs when present, else keep previous section body.
        prev_by_num = {
            str(sec.get("number") or ""): sec
            for sec in previous.get("sections") or []
            if isinstance(sec, dict)
        }
        merged_sections = []
        for sec in document.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            num = str(sec.get("number") or "")
            prev = prev_by_num.get(num)
            if prev and not _section_has_body(sec) and _section_has_body(prev):
                merged_sections.append(prev)
            else:
                merged_sections.append(sec)
        document["sections"] = merged_sections
        for key in ("code", "version", "year", "meta"):
            if previous.get(key) and not document.get(key):
                document[key] = previous[key]
    return document


# --- internals -----------------------------------------------------------------


def _normalize_blocks(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        process_id = _clean(item.get("processId") or item.get("id")) or f"p{index}"
        block_id = _clean(item.get("id")) or f"b-{process_id}"
        if block_id in seen:
            continue
        seen.add(block_id)
        smart_raw = item.get("smart") if isinstance(item.get("smart"), dict) else {}
        smart = {
            key: (str(smart_raw.get(key) or "missing") if str(smart_raw.get(key) or "") in SMART_STATUSES else "missing")
            for key in SMART_KEYS
        }
        status = str(item.get("status") or "pending")
        if status not in BLOCK_STATUSES:
            status = "pending"
        elements = item.get("elements") if isinstance(item.get("elements"), dict) else {}
        out.append(
            {
                "id": block_id,
                "processId": process_id,
                "title": _clean(item.get("title")) or process_id,
                "sourceRefs": item.get("sourceRefs") if isinstance(item.get("sourceRefs"), list) else [],
                "elements": elements,
                "smart": smart,
                "status": status,
            }
        )
    return out


def _normalize_rounds(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "open")
        if status not in ROUND_STATUSES:
            status = "open"
        qids = item.get("questionIds") if isinstance(item.get("questionIds"), list) else []
        out.append(
            {
                "index": int(item.get("index") or len(out) + 1),
                "questionIds": [str(q).strip() for q in qids if str(q).strip()],
                "status": status,
            }
        )
    return out


def _normalize_round_questions(raw: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        text = _clean(item.get("text") or item.get("question") or item.get("message"))
        if not text:
            continue
        qid = _clean(item.get("id") or item.get("questionId")) or f"q{index}"
        options = item.get("options") if isinstance(item.get("options"), list) else []
        out.append(
            {
                "id": qid,
                "processId": _clean(item.get("processId") or item.get("functionId")),
                "field": _clean(item.get("field")),
                "text": text,
                "smartKey": _clean(item.get("smartKey")).upper()[:1] or "",
                "options": [str(opt).strip() for opt in options if str(opt).strip()][:8],
                "answer": _clean(item.get("answer")),
                "status": "answered" if _clean(item.get("answer")) else "open",
            }
        )
    return out


def _merge_blocks(current: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["id"]: dict(item) for item in current}
    for item in incoming:
        existing = by_id.get(item["id"])
        if existing is None:
            by_id[item["id"]] = dict(item)
            continue
        existing["title"] = item.get("title") or existing.get("title")
        if item.get("sourceRefs"):
            existing["sourceRefs"] = item["sourceRefs"]
        if item.get("elements"):
            merged_el = dict(existing.get("elements") or {})
            for key, value in (item.get("elements") or {}).items():
                if value:
                    merged_el[key] = value
            existing["elements"] = merged_el
        by_id[item["id"]] = existing
    return list(by_id.values())


def _compute_progress(pipeline: dict[str, Any]) -> int:
    stage = pipeline.get("stage") or "upload"
    stage_weights = {
        "upload": 5,
        "extract": 15,
        "select": 25,
        "interview": 40,
        "assemble": 85,
        "done": 100,
    }
    base = stage_weights.get(stage, 5)
    if stage == "interview":
        round_n = int(pipeline.get("round") or 0)
        min_r = int(pipeline.get("minRounds") or MIN_ROUNDS)
        base = 40 + min(40, int(40 * min(round_n, min_r) / max(1, min_r)))
        blocks = pipeline.get("blocks") or []
        selected = set(pipeline.get("selectedProcessIds") or [])
        relevant = [b for b in blocks if not selected or _clean(b.get("processId")) in selected]
        if relevant:
            done = sum(1 for b in relevant if b.get("status") == "done")
            base = min(84, base + int(10 * done / len(relevant)))
    return max(0, min(100, base))


def _stage_rank(stage: str) -> int:
    try:
        return PIPELINE_STAGES.index(stage)
    except ValueError:
        return 0


def _smart_level(text: str, *, concrete: bool = False, measurable: bool = False, timed: bool = False) -> str:
    value = (text or "").strip()
    if not value or value.lower() in {"", "-", "нет", "неизвестно", "tbd"}:
        return "missing"
    lower = value.lower()
    if concrete and not any(marker in lower for marker in _CONCRETE_MARKERS) and len(value) < 24:
        return "partial"
    if measurable and not any(marker in lower for marker in _MEASURABLE_MARKERS):
        return "partial" if len(value) >= 12 else "missing"
    if timed and not any(re.search(pat, lower) for pat in _TIME_MARKERS):
        return "partial" if len(value) >= 8 else "missing"
    if len(value) < 8:
        return "partial"
    return "done"


def _block_status_from_smart(smart: dict[str, str], block: dict[str, Any]) -> str:
    values = [smart.get(key, "missing") for key in SMART_KEYS]
    if all(v == "done" for v in values):
        return "done"
    if any(v != "missing" for v in values):
        return "active"
    return str(block.get("status") or "pending") if block.get("status") in BLOCK_STATUSES else "pending"


def _process_for_block(block: dict[str, Any], state: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(state, dict):
        return None
    pid = _clean(block.get("processId"))
    for key in ("processes", "functions"):
        for item in state.get(key) or []:
            if not isinstance(item, dict):
                continue
            if _clean(item.get("id") or item.get("processId") or item.get("functionId")) == pid:
                return item
    return None


def _apply_answer_to_facts(state: dict[str, Any], entry: dict[str, Any]) -> None:
    process_id = _clean(entry.get("processId"))
    field = _clean(entry.get("field"))
    answer = _clean(entry.get("answer"))
    if not answer:
        return
    field_map = {
        "tool": "workLocation",
        "workLocation": "workLocation",
        "periodicity": "frequency",
        "frequency": "frequency",
        "trigger": "trigger",
        "triggerAction": "trigger",
        "steps": "steps",
        "userAction": "steps",
        "controls": "controls",
        "inputs": "inputs",
        "outputs": "outputs",
    }
    fact_field = field_map.get(field)
    for process in state.get("processes") or []:
        if not isinstance(process, dict):
            continue
        pid = _clean(process.get("id"))
        if process_id and pid != process_id:
            continue
        if fact_field:
            facts = process.setdefault("knownFacts", {})
            if not isinstance(facts, dict):
                facts = {}
                process["knownFacts"] = facts
            if fact_field == "steps":
                current = facts.get("steps")
                if isinstance(current, list):
                    current.append(answer)
                else:
                    facts["steps"] = [answer]
            else:
                facts[fact_field] = answer
        if not process_id:
            break


def _section_has_body(section: dict[str, Any]) -> bool:
    if section.get("paragraphs") or section.get("items") or section.get("tables"):
        return True
    nested = section.get("sections")
    return isinstance(nested, list) and any(isinstance(x, dict) and _section_has_body(x) for x in nested)


def _keyword_window(text: str, keyword: str, radius: int = 1500) -> str:
    if not text:
        return ""
    lower = text.lower()
    key = keyword.lower()
    idx = lower.find(key)
    if idx < 0:
        # try first meaningful token
        token = next((part for part in re.split(r"\W+", key) if len(part) >= 4), "")
        idx = lower.find(token) if token else -1
    if idx < 0:
        return text[: min(len(text), radius * 2)]
    start = max(0, idx - radius)
    end = min(len(text), idx + len(keyword) + radius)
    return text[start:end]


def _text_join(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, list):
            chunks.extend(_clean(item) for item in part if _clean(item))
        else:
            value = _clean(part)
            if value:
                chunks.append(value)
    return " | ".join(chunks)


def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean(item) for item in value if _clean(item)]
    text = _clean(value)
    return [text] if text else []


def _clean(value: Any) -> str:
    return str(value or "").strip()
