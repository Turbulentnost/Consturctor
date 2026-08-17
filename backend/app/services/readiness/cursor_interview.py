from __future__ import annotations

import ast
import json
import re
from typing import Any

from app.clients import cursor as cursor_client
from app.clients.cursor import CursorAgentError
from app.config import settings
from app.services.readiness.llm_interview import (
    MAX_TURNS_PER_FUNCTION,
    _fallback_response,
    _normalize_response,
)


def generate_initial_question(
    context: dict,
    pending_questions: list[dict],
    *,
    cursor_agent_id: str = "",
) -> dict:
    """Сформировать первое сообщение интервью через Cursor (или fallback на сохранённый вопрос)."""
    payload_hint = _interview_contract_hint()
    prompt = (
        "Ты Cursor Agent в живом диалоге уточнения регламента для ИИ-агента.\n"
        "Сформируй ОДИН понятный вопрос пользователю по текущему пункту, "
        "с кратким контекстом из блоков документа.\n"
        "Ответ должен закрывать пробел процесса (система, вход, условие, результат и т.п.), "
        "чтобы агент мог выполнить функцию без догадок.\n"
        f"{payload_hint}\n\n"
        f"Контекст:\n{_json_dump(_base_payload(context, pending_questions))}"
    )
    return _cursor_or_fallback(
        prompt,
        context,
        pending_questions,
        cursor_agent_id=cursor_agent_id,
        answer="",
    )


def adapt_after_answer(
    context: dict,
    pending_questions: list[dict],
    *,
    answer: str,
    history: list[dict],
    turn_count: int,
    cursor_agent_id: str = "",
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
            "userAnswer": answer,
            "history": history[-12:],
            "turnCount": turn_count,
            "maxTurns": MAX_TURNS_PER_FUNCTION,
        }
    )
    prompt = (
        "Ты Cursor Agent в живом диалоге уточнения регламента.\n"
        "Проанализируй ответ пользователя.\n"
        "Если ответ закрывает текущий и другие вопросы по этой функции — укажи их id в answeredQuestionIds.\n"
        "Если процесс уже достаточно понятен для выполнения функции ИИ-агентом — stopInterview=true.\n"
        "Иначе задай СЛЕДУЮЩИЙ конкретный процессный вопрос в assistantMessage "
        "(с контекстом пункта регламента, без служебных id вроде Q-001/CUR-Q в тексте).\n"
        "Не спрашивай то, на что пользователь уже ответил.\n"
        f"{_interview_contract_hint()}\n\n"
        f"Контекст:\n{_json_dump(payload)}"
    )
    return _cursor_or_fallback(
        prompt,
        context,
        pending_questions,
        cursor_agent_id=cursor_agent_id,
        answer=answer,
    )


def _interview_contract_hint() -> str:
    return (
        "Верни строго JSON без markdown:\n"
        "{"
        '"assistantMessage":"...",'
        '"quickAnswers":["..."],'
        '"answeredQuestionIds":["..."],'
        '"remainingQuestionIds":["..."],'
        '"newQuestions":[{"question":"...","targetField":"inputs","reason":"..."}],'
        '"stopInterview":false,'
        '"isProcessClear":false,'
        '"reason":"..."'
        "}"
    )


def _base_payload(context: dict, pending_questions: list[dict]) -> dict:
    return {
        "draft": context.get("draft") or {},
        "function": context.get("function") or {},
        "blocks": context.get("blocks") or context.get("affectedBlocks") or [],
        "currentQuestion": context.get("question") or {},
        "pendingQuestions": pending_questions,
        "responseLanguage": "ru",
    }


def _cursor_or_fallback(
    prompt: str,
    context: dict,
    pending_questions: list[dict],
    *,
    cursor_agent_id: str,
    answer: str,
) -> dict:
    try:
        raw = _run_cursor_prompt(prompt, cursor_agent_id=cursor_agent_id)
        data = _parse_json_object(raw)
        if isinstance(data, dict):
            normalized = _normalize_response(data, pending_questions)
            if not normalized.get("assistantMessage"):
                raise CursorAgentError("Cursor вернул пустой assistantMessage")
            normalized["source"] = "cursor_agent"
            return normalized
    except Exception as exc:  # noqa: BLE001 - interview must keep working offline.
        fallback = _fallback_response(context, pending_questions, answer=answer)
        fallback["warnings"] = [f"Cursor interview unavailable: {exc}"]
        fallback["source"] = "fallback"
        return fallback
    return _fallback_response(context, pending_questions, answer=answer)


def _run_cursor_prompt(prompt: str, *, cursor_agent_id: str) -> str:
    model = settings.cursor_regulation_model
    agent_id = (cursor_agent_id or "").strip()
    run_id = ""
    if agent_id:
        try:
            run = cursor_client.create_run(agent_id, prompt=prompt, mode="agent")
            run_id = str(run.get("id") or "")
        except CursorAgentError:
            agent_id = ""
    if not agent_id or not run_id:
        created = cursor_client.create_agent(
            prompt=prompt,
            model_id=model,
            name="Уточнение регламента",
            mode="agent",
            model_params=[{"id": "fast", "value": "true"}],
        )
        agent = created.get("agent") if isinstance(created.get("agent"), dict) else {}
        run = created.get("run") if isinstance(created.get("run"), dict) else {}
        agent_id = str(agent.get("id") or "")
        run_id = str(run.get("id") or "")
        if not agent_id or not run_id:
            raise CursorAgentError("Cursor API не вернул agent/run id")
    final = cursor_client.wait_for_run(agent_id, run_id, timeout_seconds=180.0)
    return str(final.get("result") or "")


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    try:
        parsed = ast.literal_eval(text)
        return parsed if isinstance(parsed, dict) else {}
    except (SyntaxError, ValueError):
        pass
    match = re.search(r"\{.*\}", text, flags=re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        try:
            parsed = ast.literal_eval(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except (SyntaxError, ValueError):
            return {}


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)
