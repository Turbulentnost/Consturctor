from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.trigger import ScheduleDraftOut, ScheduleTriggerSpec
from app.services.agent_passport import llm as llm_service
from app.services.workflows.plan_models import WorkflowPlan

logger = logging.getLogger(__name__)

_UNITS = ("minutes", "hours", "days")
WHEN_TO_RUN_QUESTION = "Когда запускать этого агента?"
WHEN_TO_RUN_OPTIONS = [
    "только вручную из чата",
    "каждый час",
    "раз в день",
    "при конкретном событии — напишу каком",
]
WHEN_TO_RUN_WHY = "В материалах не сказано, когда запускать агента. Без этого он не должен стартовать сам."
_MANUAL_HINTS = ("по кнопк", "вручную", "по запрос", "из чата", "только вручн")
_WHEN_QUESTION_HINTS = (
    "когда запуска",
    "как часто",
    "по расписан",
    "только вручн",
    WHEN_TO_RUN_QUESTION.casefold(),
)


def trigger_chip_label(spec: ScheduleTriggerSpec) -> str:
    kind = (spec.kind or "").strip().casefold()
    if kind == "interval":
        value = spec.interval_value or 0
        unit = (spec.interval_unit or "hours").strip().casefold()
        amount = int(value) if float(value).is_integer() else value
        if unit == "minutes":
            if amount == 1:
                return "каждую минуту"
            return f"каждые {amount} мин"
        if unit == "days":
            if amount == 1:
                return "ежедневно"
            return f"каждые {amount} дн."
        if amount == 1:
            return "каждый час"
        return f"каждые {amount} ч"
    if kind == "datetime":
        clock = _time_from_at(spec.at)
        if not spec.once and clock:
            return f"ежедневно в {clock}"
        if clock and not _has_date(spec.at):
            return f"ежедневно в {clock}"
        pretty = _pretty_datetime(spec.at)
        return pretty or "в указанное время"
    condition = _short_event_condition(spec.condition or spec.message)
    if condition:
        return f"при событии: {condition}"
    return "по событию"


def explicit_when_to_run(*parts: str) -> bool:
    """True только если человек или ТЗ явно сказали, когда запускать."""
    blob = "\n".join(str(part or "") for part in parts if str(part or "").strip())
    if not blob.strip():
        return False
    low = blob.casefold().replace("ё", "е")
    if any(hint in low for hint in _MANUAL_HINTS):
        return True
    if _parse_interval(low) is not None:
        return True
    if re.search(r"(ежедневн|каждый день|раз в день).{0,20}\d{1,2}[:.]\d{2}", low):
        return True
    if re.search(r"триггер:\s*\S+", blob, re.IGNORECASE):
        hint = _passport_trigger_line(blob)
        if hint and _parse_trigger_hint(hint) is not None:
            return True
    if re.search(r"событийн.{0,30}триггер|триггер.{0,30}событи|событие вместо расписания", low):
        return True
    if _is_explicit_event_condition(blob) and (
        len(low) < 160 or _event_is_scheduled(low)
    ):
        return True
    return False


def already_asks_when_to_run(draft: dict[str, Any] | None) -> bool:
    for item in (draft or {}).get("required_clarifications") or []:
        if isinstance(item, str):
            question = item
        elif isinstance(item, dict):
            question = str(item.get("question") or "")
        else:
            continue
        folded = question.casefold().replace("ё", "е")
        if any(hint in folded for hint in _WHEN_QUESTION_HINTS):
            return True
    return False


def is_when_to_run_question(question: str) -> bool:
    folded = (question or "").casefold().replace("ё", "е")
    return bool(folded) and any(hint in folded for hint in _WHEN_QUESTION_HINTS)


def triggers_from_when_answer(answer: str) -> list[ScheduleTriggerSpec]:
    spec = _parse_trigger_hint(answer or "")
    return [spec] if spec is not None else []


def _trigger_from_when_to_run(when_to_run: str) -> ScheduleTriggerSpec | None:
    """Trigger detected from the playbook when_to_run text.

    Try the strict parser first. If the text is not a manual-only run and the
    strict parser did not recognize a schedule, surface it as an editable event
    so the detected trigger is not silently dropped from the passport.
    """
    raw = (when_to_run or "").strip()
    if not raw:
        return None
    low = raw.casefold().replace("\u0451", "\u0435")
    if any(hint in low for hint in _MANUAL_HINTS):
        return None
    parsed = _parse_trigger_hint(raw)
    if parsed is not None:
        return parsed
    if len(low) < 6:
        return None
    condition = _short_event_condition(raw) or raw
    return ScheduleTriggerSpec(kind="event", message="", condition=condition[:120].strip(), once=False)


def draft_after_demo(
    *,
    title: str,
    notes: str,
    playbook: dict[str, Any],
    last_result: str = "",
    work: dict[str, Any] | None = None,
    answered_scope: str = "",
) -> ScheduleDraftOut:
    from app.services.workflows.prompts import title_from_materials

    name = str(playbook.get("name") or "").strip() or title_from_materials(
        notes=notes, fallback=title or "ИИ-агент"
    )
    goal = str(playbook.get("expected_result") or playbook.get("instructions") or "").strip()
    if len(goal) > 280:
        goal = goal[:280].rsplit(" ", 1)[0].strip()
    ground = "\n".join(part for part in (notes, answered_scope) if str(part or "").strip())
    triggers: list[ScheduleTriggerSpec] = []
    raw_triggers = playbook.get("triggers") if isinstance(playbook.get("triggers"), list) else []
    for item in raw_triggers:
        if not isinstance(item, dict):
            continue
        spec = _normalize_spec(item)
        if spec is not None and _trigger_grounded(spec, ground):
            triggers.append(spec)
    work = work or {}
    for line in work.get("schedule") or []:
        parsed = _parse_trigger_hint(str(line))
        if parsed is not None and _trigger_grounded(parsed, ground) and not _same_trigger(parsed, triggers):
            triggers.append(parsed)
    if not triggers:
        hint = _passport_trigger_line(notes)
        parsed = _parse_trigger_hint(hint) if hint else None
        if parsed is not None and _trigger_grounded(parsed, ground):
            triggers.append(parsed)
    if not triggers:
        for line in (answered_scope or "").splitlines():
            ask, _, reply = line.partition("→")
            reply = reply.strip() or line.strip().lstrip("- ")
            if not reply:
                continue
            if not (is_when_to_run_question(ask) or explicit_when_to_run(reply)):
                continue
            for parsed in triggers_from_when_answer(reply):
                if not _same_trigger(parsed, triggers):
                    triggers.append(parsed)
    if not triggers:
        detected = _trigger_from_when_to_run(str(playbook.get("when_to_run") or ""))
        if detected is not None and not _same_trigger(detected, triggers):
            triggers.append(detected)
    return ScheduleDraftOut(name=name or title or "ИИ-агент", goal=goal, triggers=triggers)


def propose_schedule_draft(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
) -> ScheduleDraftOut:
    from app.services.workflows.service import _get_owned

    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    plan = WorkflowPlan.from_dict(row.plan_json or {})
    local = dict(row.local_run or {})
    from app.services.workflows.prompts import _answered_scope_lines

    existing_raw = local.get("schedule_draft") if isinstance(local.get("schedule_draft"), dict) else {}
    existing = _normalize_draft(existing_raw, ScheduleDraftOut()) if existing_raw else None
    playbook_draft = local.get("playbook_draft") if isinstance(local.get("playbook_draft"), dict) else {}
    when_to_run = str(playbook_draft.get("when_to_run") or "").strip()
    ground = "\n".join(
        part
        for part in (row.notes or "", row.document_text or "", _answered_scope_lines(plan), when_to_run)
        if str(part).strip()
    )
    if existing is not None and existing.triggers:
        kept = [item for item in existing.triggers if _trigger_grounded(item, ground)]
        if kept:
            if (row.title or "").strip() and existing.name in {"", "ИИ-агент", "notes.txt", "notes"}:
                existing = existing.model_copy(update={"name": row.title, "triggers": kept})
            else:
                existing = existing.model_copy(update={"triggers": kept})
            local["schedule_draft"] = existing.model_dump()
            row.local_run = local
            db.commit()
            return existing
        existing = existing.model_copy(update={"triggers": []})
    fallback = _heuristic_draft(row.title or "", plan, row.notes or "", row.last_result or "")
    if existing is not None:
        fallback = ScheduleDraftOut(
            name=existing.name or fallback.name,
            goal=existing.goal or fallback.goal,
            triggers=existing.triggers or fallback.triggers,
        )
    draft = _llm_draft(
        title=row.title or "",
        plan=plan,
        notes=row.notes or "",
        last_result=row.last_result or "",
        fallback=fallback,
    )
    draft = draft.model_copy(
        update={"triggers": [item for item in draft.triggers if _trigger_grounded(item, ground)]}
    )
    if not draft.triggers and when_to_run:
        detected = _trigger_from_when_to_run(when_to_run)
        if detected is not None:
            draft = draft.model_copy(update={"triggers": [detected]})
    local["schedule_draft"] = draft.model_dump()
    row.local_run = local
    db.commit()
    return draft


def _heuristic_draft(title: str, plan: WorkflowPlan, notes: str, last_result: str) -> ScheduleDraftOut:
    from app.services.workflows.prompts import is_placeholder_title, title_from_materials

    name = (title or plan.title or "").strip()
    if not name or is_placeholder_title(name):
        name = title_from_materials(notes=notes, fallback=plan.title or "ИИ-агент")
    goal = (plan.goal or "").strip()
    trigger_line = _passport_trigger_line(notes)
    triggers: list[ScheduleTriggerSpec] = []
    if trigger_line:
        parsed = _parse_trigger_hint(trigger_line)
        if parsed is not None:
            triggers.append(parsed)
    return ScheduleDraftOut(name=name, goal=goal, triggers=triggers)


def _passport_trigger_line(notes: str) -> str:
    for line in (notes or "").splitlines():
        stripped = line.strip()
        if stripped.casefold().startswith("триггер:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _parse_trigger_hint(text: str) -> ScheduleTriggerSpec | None:
    raw = (text or "").strip()
    if not raw:
        return None
    low = raw.casefold().replace("ё", "е")
    if any(k in low for k in _MANUAL_HINTS):
        return None
    interval = _parse_interval(low)
    if interval is not None:
        value, unit = interval
        return ScheduleTriggerSpec(
            kind="interval",
            message="",
            interval_value=value,
            interval_unit=unit,
            once=False,
        )
    daily = re.search(r"(?:ежедневн|каждый день|раз в день).{0,20}(\d{1,2})[:.](\d{2})", low)
    if daily:
        clock = f"{int(daily.group(1)):02d}:{int(daily.group(2)):02d}"
        return ScheduleTriggerSpec(kind="datetime", message="", at=clock, once=False)
    if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}", raw):
        return ScheduleTriggerSpec(kind="datetime", message=raw, at=raw, once=True)
    if not _is_explicit_event_condition(raw):
        return None
    condition = _short_event_condition(raw)
    if not condition:
        return None
    return ScheduleTriggerSpec(kind="event", message="", condition=condition, once=False)


def _parse_interval(low: str) -> tuple[float, str] | None:
    folded = (low or "").casefold().replace("ё", "е")
    if re.search(r"раз в день|ежедневн|каждый день", folded) and not re.search(
        r"\d+(?:[.,]\d+)?\s*(минут|мин|час)", folded
    ):
        return 1, "days"
    if re.search(r"каждый час|раз в час|ежечасн", folded) and not re.search(
        r"\d+(?:[.,]\d+)?\s*(минут|мин)", folded
    ):
        return 1, "hours"
    match = re.search(
        r"(?:каждые|каждый|каждую|раз в)?\s*(\d+(?:[.,]\d+)?)\s*(минут|мин|час|дня|дней|день|сутк)",
        folded,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit_raw = match.group(2)
    if unit_raw.startswith("мин"):
        return value, "minutes"
    if unit_raw.startswith("час"):
        return value, "hours"
    return value, "days"


def _is_explicit_event_condition(text: str) -> bool:
    low = (text or "").casefold().replace("ё", "е")
    if not low or len(low) < 6:
        return False
    if "напишу каком" in low:
        return False
    if low in {"по событию", "событие", "поступило новое событие по процессу"}:
        return False
    if "событие по процессу" in low:
        return False
    if re.match(r"при событи", low) and not any(
        token in low for token in ("письм", "файл", "сообщен", "входящ")
    ):
        return False
    if re.search(r"^(при|когда|если)\s+\S+", low):
        return True
    return any(token in low for token in ("письм", "файл", "сообщен", "входящ"))


def _event_is_scheduled(low: str) -> bool:
    return bool(
        re.search(r"триггер:\s*", low)
        or re.search(r"запускать.{0,40}(при|когда|если)", low)
        or re.search(r"(запуск|запускать).{0,20}по письм", low)
        or "по письм" in low
    )


def _trigger_grounded(spec: ScheduleTriggerSpec, ground: str) -> bool:
    low = (ground or "").casefold().replace("ё", "е")
    if not low.strip():
        return False
    if spec.kind == "interval":
        parsed = _parse_interval(low)
        if parsed is None:
            return False
        value, unit = parsed
        return float(spec.interval_value or 0) == float(value) and (
            spec.interval_unit or "hours"
        ).casefold() == unit
    if spec.kind == "datetime":
        clock = _time_from_at(spec.at)
        return bool(clock and _time_from_at(ground))
    if spec.kind == "event":
        if not _is_explicit_event_condition(spec.condition):
            return False
        return _event_is_scheduled(low)
    return False


def _llm_draft(
    *,
    title: str,
    plan: WorkflowPlan,
    notes: str,
    last_result: str,
    fallback: ScheduleDraftOut,
) -> ScheduleDraftOut:
    prompt = (
        "По материалам агента предложи паспорт запуска: название, цель и когда запускать.\n"
        "Верни ТОЛЬКО JSON:\n"
        "{\n"
        '  "name": "string",\n'
        '  "goal": "string",\n'
        '  "triggers": [\n'
        "    {\n"
        '      "kind": "interval|event|datetime",\n'
        '      "message": "задача при срабатывании",\n'
        '      "interval_value": 0,\n'
        '      "interval_unit": "minutes|hours|days",\n'
        '      "condition": "событие: изменён файл / получено письмо",\n'
        '      "at": "ISO дата-время или пусто",\n'
        '      "once": true\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Правила:\n"
        "- Не выдумывай доступы, URL и пароли.\n"
        "- name — человеческое имя агента из паспорта, не имя файла (notes.txt).\n"
        "- Если в материалах нет расписания — triggers: []. Тогда агент только вручную из чата.\n"
        "- Можно несколько триггеров.\n"
        "- interval — каждые N минут/часов/дней.\n"
        "- event — короткая фраза до 80 символов, не копируй абзац ТЗ.\n"
        "- datetime — конкретные дата и время; once=false значит ежедневно в это время.\n"
        "- message не дублируй condition.\n\n"
        f"Название: {title or fallback.name}\n"
        f"Цель плана: {plan.goal or fallback.goal}\n"
        f"Заметки/паспорт:\n{(notes or '')[:4000]}\n\n"
        f"Результат теста:\n{(last_result or '')[:4000]}\n"
    )
    raw = llm_service.generate(
        prompt,
        system="Ты заполняешь паспорт запуска ИИ-агента. Отвечай только JSON.",
        max_tokens=800,
        quick=True,
    )
    parsed = _extract_json(raw or "")
    if parsed is None:
        return fallback
    return _normalize_draft(parsed, fallback)


def _extract_json(text: str) -> dict[str, Any] | None:
    stripped = (text or "").strip()
    if not stripped:
        return None
    if "```" in stripped:
        parts = stripped.split("```")
        for i, chunk in enumerate(parts):
            if i % 2 == 1:
                body = chunk
                if body.lstrip().lower().startswith("json"):
                    body = body.lstrip()[4:]
                try:
                    data = json.loads(body.strip())
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    continue
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(stripped[start : end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            return None
    return None


def _normalize_draft(data: dict[str, Any], fallback: ScheduleDraftOut) -> ScheduleDraftOut:
    name = str(data.get("name") or fallback.name or "ИИ-агент").strip() or fallback.name
    goal = str(data.get("goal") or fallback.goal or "").strip()
    items = data.get("triggers")
    triggers: list[ScheduleTriggerSpec] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            spec = _normalize_spec(item)
            if spec is not None:
                triggers.append(spec)
    return ScheduleDraftOut(name=name, goal=goal, triggers=triggers)


def _normalize_spec(item: dict[str, Any]) -> ScheduleTriggerSpec | None:
    kind = str(item.get("kind") or "").strip().casefold()
    if kind not in {"interval", "event", "datetime"}:
        if item.get("interval_value") or item.get("interval_seconds"):
            kind = "interval"
        elif item.get("at"):
            kind = "datetime"
        elif item.get("condition"):
            kind = "event"
        else:
            return None
    unit = str(item.get("interval_unit") or "hours").strip().casefold()
    if unit not in _UNITS:
        unit = "hours"
    try:
        value = float(item.get("interval_value") or 0)
    except (TypeError, ValueError):
        value = 0
    if kind == "interval" and value <= 0:
        return None
    condition = _short_event_condition(str(item.get("condition") or "").strip())
    at = str(item.get("at") or "").strip()
    if kind == "event" and not condition:
        return None
    if kind == "datetime" and not at:
        return None
    message = str(item.get("message") or "").strip()
    if kind == "event" and (message == condition or len(message) > 160):
        message = ""
    return ScheduleTriggerSpec(
        kind=kind,
        message=message,
        interval_value=value,
        interval_unit=unit,
        condition=condition,
        at=at,
        once=bool(item.get("once", kind == "datetime")),
    )


def _short_event_condition(text: str) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    if len(raw) > 80:
        cut = raw[:80].rsplit(" ", 1)[0].strip()
        return (cut or raw[:80]).rstrip(".,;") 
    return raw


def _same_trigger(spec: ScheduleTriggerSpec, existing: list[ScheduleTriggerSpec]) -> bool:
    for item in existing:
        if item.kind == spec.kind and item.interval_value == spec.interval_value and item.interval_unit == spec.interval_unit:
            if spec.kind != "event" or item.condition == spec.condition:
                return True
        if item.kind == spec.kind == "datetime" and item.at == spec.at:
            return True
    return False


def _time_from_at(value: str) -> str:
    raw = (value or "").strip()
    match = re.search(r"(\d{1,2})[:.](\d{2})", raw)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return ""
    return f"{hour:02d}:{minute:02d}"


def _has_date(value: str) -> bool:
    raw = (value or "").strip()
    return bool(re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}", raw))


def _pretty_datetime(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    clock = _time_from_at(raw)
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        return f"{match.group(3)}.{match.group(2)}.{match.group(1)}" + (f" {clock}" if clock else "")
    match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", raw)
    if match:
        return f"{int(match.group(1)):02d}.{int(match.group(2)):02d}.{match.group(3)}" + (
            f" {clock}" if clock else ""
        )
    return clock or raw[:40]
