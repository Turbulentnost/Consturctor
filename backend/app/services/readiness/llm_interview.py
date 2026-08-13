from __future__ import annotations

from typing import Any

from app.services.role_matching.claudehub_client import _load_json, _post_json


MAX_TURNS_PER_FUNCTION = 6


def generate_initial_question(context: dict, pending_questions: list[dict]) -> dict:
    payload = _base_payload(context, pending_questions)
    payload["instruction"] = (
        "Ты помогаешь уточнить регламент для создания ИИ-агента. "
        "Используй только переданные блоки документа и роль/отдел пользователя. "
        "Сформируй один понятный вопрос одним сообщением, с контекстом пункта регламента. "
        "Верни JSON: {assistantMessage, quickAnswers, remainingQuestionIds, stopInterview, reason}. "
        "quickAnswers должны быть короткими вариантами ответа для пользователя."
    )
    return _llm_or_fallback(payload, context, pending_questions)


def adapt_after_answer(
    context: dict,
    pending_questions: list[dict],
    *,
    answer: str,
    history: list[dict],
    turn_count: int,
) -> dict:
    if turn_count >= MAX_TURNS_PER_FUNCTION:
        return {
            "assistantMessage": "Понял. Уточнений по этому блоку достаточно, можно перейти к следующему вопросу.",
            "quickAnswers": [],
            "answeredQuestionIds": [str(item.get("questionId") or "") for item in pending_questions[:1]],
            "remainingQuestionIds": [str(item.get("questionId") or "") for item in pending_questions[1:]],
            "stopInterview": True,
            "source": "limit",
        }
    payload = _base_payload(context, pending_questions)
    payload.update(
        {
            "instruction": (
                "Проанализируй ответ пользователя на уточняющий вопрос по регламенту. "
                "Если ответ закрывает другие вопросы по этой же функции, укажи их id в answeredQuestionIds. "
                "Если бизнес-процесс уже понятен достаточно, верни stopInterview=true. "
                "Иначе в assistantMessage задай СЛЕДУЮЩИЙ уточняющий вопрос одним сообщением "
                "с контекстом пункта регламента. "
                "Не пиши, что вопрос закрыт, не упоминай id вопросов (Q-001 и т.п.), "
                "не пиши «это закрывает вопрос» и не пересказывай служебные поля вроде trigger. "
                "Верни JSON: {assistantMessage, quickAnswers, answeredQuestionIds, remainingQuestionIds, "
                "newQuestions, stopInterview, isProcessClear, reason}. "
                "Не задавай бесконечные уточнения и не спрашивай то, на что пользователь уже ответил."
            ),
            "userAnswer": answer,
            "history": history[-12:],
            "turnCount": turn_count,
            "maxTurns": MAX_TURNS_PER_FUNCTION,
        }
    )
    return _llm_or_fallback(payload, context, pending_questions, answer=answer)


def _base_payload(context: dict, pending_questions: list[dict]) -> dict:
    return {
        "draft": context.get("draft") or {},
        "function": context.get("function") or {},
        "blocks": context.get("blocks") or context.get("affectedBlocks") or [],
        "currentQuestion": context.get("question") or {},
        "pendingQuestions": pending_questions,
        "responseLanguage": "ru",
    }


def _llm_or_fallback(
    payload: dict,
    context: dict,
    pending_questions: list[dict],
    *,
    answer: str = "",
) -> dict:
    try:
        data = _load_json(_post_json(payload, timeout=90.0))
        if isinstance(data, dict):
            normalized = _normalize_response(data, pending_questions)
            normalized["source"] = "claudehub"
            return normalized
    except Exception as exc:  # noqa: BLE001 - clarification must keep working offline.
        fallback = _fallback_response(context, pending_questions, answer=answer)
        fallback["warnings"] = [f"LLM interview unavailable: {exc}"]
        return fallback
    return _fallback_response(context, pending_questions, answer=answer)


def _normalize_response(data: dict[str, Any], pending_questions: list[dict]) -> dict:
    pending_ids = [str(item.get("questionId") or "") for item in pending_questions if item.get("questionId")]
    answered = _ids(data.get("answeredQuestionIds"), pending_ids)
    remaining = _ids(data.get("remainingQuestionIds"), pending_ids)
    if not remaining:
        remaining = [qid for qid in pending_ids if qid not in answered]
    quick = [str(item).strip() for item in data.get("quickAnswers") or [] if str(item).strip()]
    return {
        "assistantMessage": str(data.get("assistantMessage") or "").strip(),
        "quickAnswers": quick[:5],
        "answeredQuestionIds": answered,
        "remainingQuestionIds": remaining,
        "newQuestions": [item for item in data.get("newQuestions") or [] if isinstance(item, dict)][:3],
        "stopInterview": bool(data.get("stopInterview") or data.get("isProcessClear")),
        "isProcessClear": bool(data.get("isProcessClear") or data.get("stopInterview")),
        "reason": str(data.get("reason") or ""),
    }


def _ids(value: object, allowed: list[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed_set = set(allowed)
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text and text in allowed_set and text not in out:
            out.append(text)
    return out


def _fallback_response(context: dict, pending_questions: list[dict], *, answer: str = "") -> dict:
    # Всегда опираемся на текущий вопрос сессии, а не на первый pending —
    # иначе закрывается чужой id, а исходный вопрос задаётся снова.
    current = context.get("question") or (pending_questions[0] if pending_questions else {})
    current_id = str(current.get("questionId") or "")
    answered = [current_id] if answer.strip() and not _needs_clarification(answer) and current_id else []
    remaining = [str(item.get("questionId") or "") for item in pending_questions if item.get("questionId")]
    remaining = [qid for qid in remaining if qid not in answered]
    next_question = None
    message = _contextual_question(context, current)
    if answer.strip() and answered:
        next_question = next(
            (item for item in pending_questions if str(item.get("questionId") or "") in remaining),
            None,
        )
        message = _contextual_question(context, next_question) if next_question else (
            "Понял. По этому функциональному блоку достаточно информации для подготовки изменения регламента."
        )
    elif answer.strip():
        message = "Пока не хватает конкретики. Уточните правило так, чтобы его можно было прямо внести в регламент."
    quick_source = next_question or current
    return {
        "assistantMessage": message,
        "quickAnswers": _quick_answers(quick_source),
        "answeredQuestionIds": answered,
        "remainingQuestionIds": remaining,
        "newQuestions": [],
        "stopInterview": bool(answered and not remaining),
        "isProcessClear": bool(answered and not remaining),
        "reason": "fallback",
        "source": "fallback",
    }


def _contextual_question(context: dict, question: dict | None) -> str:
    if not question:
        return "По этому функциональному блоку дополнительных вопросов нет."
    draft = context.get("draft") or {}
    function = context.get("function") or {}
    blocks = context.get("blocks") or context.get("affectedBlocks") or []
    source = next((item for item in blocks if item.get("relation") == "source"), blocks[0] if blocks else {})
    position = draft.get("position") or "этой должности"
    section = source.get("section") or (question.get("sourceEvidence") or {}).get("section") or "соответствующем пункте"
    quote = source.get("text") or (question.get("sourceEvidence") or {}).get("quote") or function.get("title") or ""
    return (
        f"Для {position} в пункте «{section}» регламента указано: «{str(quote)[:420]}». "
        f"{question.get('question') or 'Что нужно уточнить для выполнения этой функции агентом?'}"
    )


def _quick_answers(question: dict) -> list[str]:
    options = [str(item).strip() for item in question.get("options") or [] if str(item).strip()]
    return options[:4] or ["Да", "Нет", "Пока неизвестно", "Для этой функции не требуется"]


def _needs_clarification(text: str) -> bool:
    clean = text.strip().casefold()
    if not clean or clean in {"не знаю", "пока неизвестно", "позже", "уточню позже"}:
        return True
    return clean in {"по ситуации", "как обычно", "на усмотрение", "пока непонятно"}
