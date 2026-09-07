"""Question queue and prefetch for continuous interview flow."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.services.regulation_creation.pipeline import (
    MAX_QUESTIONS_PER_ROUND,
    _collect_question_template,
    _collect_required_gaps_for_process,
    _collect_stage_done,
    _dedupe_round_questions,
    _drop_known_questions,
    _filter_round_questions,
    _clean,
    normalize_pipeline,
)

TARGET_QUEUE_DEPTH = 5
MIN_QUEUE_DEPTH = 3


def normalize_question_queue(state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(state) if isinstance(state, dict) else {}
    raw = out.get("questionQueue")
    out["questionQueue"] = [_normalize_queue_item(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []
    out["prefetchInProgress"] = bool(out.get("prefetchInProgress"))
    return out


def queue_depth(state: dict[str, Any]) -> int:
    return len(normalize_question_queue(state).get("questionQueue") or [])


def queue_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_question_queue(state)
    depth = len(normalized.get("questionQueue") or [])
    return {
        "questionQueue": list(normalized.get("questionQueue") or []),
        "prefetchInProgress": bool(normalized.get("prefetchInProgress")),
        "queueDepth": depth,
    }


def peek_queue_head(state: dict[str, Any]) -> dict[str, Any] | None:
    queue = normalize_question_queue(state).get("questionQueue") or []
    return dict(queue[0]) if queue else None


def all_collect_questions(state: dict[str, Any]) -> list[dict[str, Any]]:
    interview = state if isinstance(state, dict) else {}
    pipeline = normalize_pipeline(interview.get("pipeline"))
    if pipeline.get("stage") != "interview" or _collect_stage_done(pipeline):
        return []
    selected_ids = [
        str(item).strip()
        for item in (pipeline.get("selectedProcessIds") or [])
        if str(item).strip()
    ]
    if not selected_ids:
        return []
    by_id = {
        _clean(item.get("id")): item
        for item in (interview.get("processes") or [])
        if isinstance(item, dict) and _clean(item.get("id"))
    }
    questions: list[dict[str, Any]] = []
    for pid in selected_ids:
        process = by_id.get(pid)
        title = _clean((process or {}).get("title")) or pid
        for field in _collect_required_gaps_for_process(process):
            text, options, smart_key = _collect_question_template(field=field, process_title=title)
            questions.append(
                {
                    "id": f"collect-{pid}-{field}",
                    "processId": pid,
                    "field": field,
                    "text": text,
                    "smartKey": smart_key,
                    "options": options,
                    "source": "collect",
                }
            )
    return questions


def enqueue_questions(state: dict[str, Any], questions: list[Any]) -> dict[str, Any]:
    out = normalize_question_queue(state)
    pipeline = normalize_pipeline(out.get("pipeline"))
    selected = {str(item).strip() for item in (pipeline.get("selectedProcessIds") or []) if str(item).strip()}
    if pipeline.get("stage") != "interview" or (selected and pipeline.get("stage") == "select"):
        return out
    if not selected and pipeline.get("interviewPhase") != "collect":
        filtered_in = [item for item in questions if isinstance(item, dict)]
    else:
        filtered_in = _filter_round_questions(
            [item for item in questions if isinstance(item, dict)],
            selected,
        )
    filtered_in = _drop_known_questions(out, filtered_in)
    normalized = [_normalize_queue_item(item) for item in filtered_in if isinstance(item, dict)]
    deduped = _dedupe_queue_items(out, pipeline, normalized)
    if not deduped:
        return out
    out["questionQueue"] = (out.get("questionQueue") or []) + deduped
    return out


def enqueue_round_batch(state: dict[str, Any], questions: list[Any]) -> dict[str, Any]:
    pipeline = normalize_pipeline(state.get("pipeline") if isinstance(state, dict) else {})
    if not _collect_stage_done(pipeline):
        return normalize_question_queue(state)
    selected = {str(item).strip() for item in (pipeline.get("selectedProcessIds") or []) if str(item).strip()}
    filtered = _filter_round_questions(
        [item for item in questions if isinstance(item, dict)],
        selected,
    )
    filtered = _drop_known_questions(state, filtered)
    pipe = normalize_pipeline(state.get("pipeline"))
    deduped = _dedupe_round_questions(pipe, [_normalize_queue_item(item) for item in filtered])
    return enqueue_questions(state, deduped)


def replenish_queue(state: dict[str, Any], *, target: int = TARGET_QUEUE_DEPTH) -> dict[str, Any]:
    out = normalize_question_queue(state)
    pipeline = normalize_pipeline(out.get("pipeline"))
    stage = str(pipeline.get("stage") or "")
    phase = str(pipeline.get("interviewPhase") or stage)
    if stage != "interview" or phase == "select":
        out["questionQueue"] = []
        out["prefetchInProgress"] = False
        return out

    current_depth = len(out.get("questionQueue") or [])
    if current_depth >= target:
        out["prefetchInProgress"] = False
        return out

    if phase == "collect" or not _collect_stage_done(pipeline):
        candidates = all_collect_questions(out)
        out = enqueue_questions(out, candidates)
        current_depth = len(out.get("questionQueue") or [])
        out["prefetchInProgress"] = current_depth < MIN_QUEUE_DEPTH and not _collect_stage_done(
            normalize_pipeline(out.get("pipeline"))
        )
        return out

    # Rounds: queue may be filled by LLM batch; mark prefetch when shallow.
    out["prefetchInProgress"] = current_depth < MIN_QUEUE_DEPTH
    return out


def consume_queue_head(state: dict[str, Any], *, question_id: str = "") -> dict[str, Any]:
    out = normalize_question_queue(state)
    queue = out.get("questionQueue") or []
    if not queue:
        return out
    head = queue[0]
    qid = _clean(question_id or head.get("id"))
    if qid and _clean(head.get("id")) != qid:
        for index, item in enumerate(queue):
            if _clean(item.get("id")) == qid:
                out["questionQueue"] = queue[:index] + queue[index + 1 :]
                return out
        return out
    out["questionQueue"] = queue[1:]
    return out


def question_to_prefetched_reply(question: dict[str, Any]) -> str:
    message = _clean(question.get("text"))
    options = question.get("options") if isinstance(question.get("options"), list) else []
    payload = {
        "status": "need_more",
        "message": message,
        "quickAnswers": options,
        "roundQuestions": [],
        "interview": {
            "processes": [],
            "queuedQuestion": {
                "id": question.get("id"),
                "processId": question.get("processId"),
                "field": question.get("field"),
            },
        },
        "pipeline": {"stage": "interview"},
        "document": {},
    }
    return json.dumps(payload, ensure_ascii=False)


def build_fastpath_reply_from_queue(
    *,
    interview: dict[str, Any],
    pipeline: dict[str, Any],
    force_create: bool,
) -> str:
    if force_create:
        return ""
    if str(pipeline.get("stage") or "") != "interview":
        return ""
    phase = str(pipeline.get("interviewPhase") or "")
    if phase in {"select", "upload", "extract", "assemble", "done"}:
        return ""
    filled = replenish_queue(interview, target=TARGET_QUEUE_DEPTH)
    head = peek_queue_head(filled)
    if head:
        return question_to_prefetched_reply(head)
    return ""


def apply_collect_answer_to_facts(state: dict[str, Any], message: str) -> dict[str, Any]:
    out = normalize_question_queue(state)
    current = out.get("currentQuestion") if isinstance(out.get("currentQuestion"), dict) else {}
    answer = _clean(message)
    if not current or not answer:
        return out
    qid = _clean(current.get("id"))
    process_id = _clean(current.get("processId") or current.get("functionId"))
    field = _clean(current.get("field"))
    if not field and qid.startswith("collect-"):
        parts = qid.split("-", 2)
        if len(parts) == 3:
            process_id = process_id or parts[1]
            field = parts[2]
    if not field:
        return out
    from app.services.regulation_creation.pipeline import _apply_answer_to_facts

    _apply_answer_to_facts(
        out,
        {
            "processId": process_id,
            "field": field,
            "answer": answer,
        },
    )
    out["pipeline"] = normalize_pipeline(out.get("pipeline"))
    return out


def queued_question_metadata(parsed: dict[str, Any]) -> dict[str, str]:
    interview = parsed.get("interview") if isinstance(parsed.get("interview"), dict) else {}
    queued = interview.get("queuedQuestion") if isinstance(interview.get("queuedQuestion"), dict) else {}
    return {
        "id": _clean(queued.get("id")),
        "processId": _clean(queued.get("processId")),
        "field": _clean(queued.get("field")),
    }


def needs_llm_prefetch(state: dict[str, Any]) -> bool:
    pipeline = normalize_pipeline(state.get("pipeline") if isinstance(state, dict) else {})
    if pipeline.get("stage") != "interview":
        return False
    if not _collect_stage_done(pipeline):
        return False
    filled = replenish_queue(state, target=MIN_QUEUE_DEPTH)
    depth = len(filled.get("questionQueue") or [])
    if depth >= MIN_QUEUE_DEPTH:
        return False
    remaining = int(pipeline.get("maxQuestionsTotal") or 0) - int(pipeline.get("questionsAskedTotal") or 0)
    return remaining > 0


def _normalize_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    text = _clean(item.get("text") or item.get("message"))
    options = item.get("options") if isinstance(item.get("options"), list) else item.get("quickAnswers")
    if not isinstance(options, list):
        options = []
    qid = _clean(item.get("id")) or f"q-{_clean(item.get('processId'))}-{_clean(item.get('field'))}"
    return {
        "id": qid,
        "processId": _clean(item.get("processId") or item.get("functionId")),
        "field": _clean(item.get("field")),
        "text": text,
        "options": [_clean(opt) for opt in options if _clean(opt)],
        "smartKey": _clean(item.get("smartKey")),
        "source": _clean(item.get("source")) or "round",
    }


def _dedupe_queue_items(state: dict[str, Any], pipeline: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.services.regulation_creation.pipeline import _question_key

    pipe = normalize_pipeline(pipeline)
    seen = {_question_key(item) for item in pipe.get("roundQuestions") or []}
    for item in normalize_question_queue(state).get("questionQueue") or []:
        seen.add(_question_key(item))
    current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    if current:
        seen.add(_question_key(current))
    answered = {qid for qid, value in (pipe.get("questionnaire") or {}).items() if _clean(value)}
    out: list[dict[str, Any]] = []
    for item in items:
        qid = _clean(item.get("id"))
        if qid in answered:
            continue
        key = _question_key(item)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
