from __future__ import annotations

import json
import logging
import re
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.trigger import ScheduleDraftOut, ScheduleTriggerSpec
from app.services.agent_passport import llm as llm_service
from app.services.workflows.plan_models import WorkflowPlan
from app.services.workflows.service import WorkflowError, _get_owned

logger = logging.getLogger(__name__)

_UNITS = ("minutes", "hours", "days")


def propose_schedule_draft(
    db: Session,
    *,
    user_id: str,
    workflow_id: str,
) -> ScheduleDraftOut:
    row = _get_owned(db, user_id=user_id, workflow_id=workflow_id)
    plan = WorkflowPlan.from_dict(row.plan_json or {})
    fallback = _heuristic_draft(row.title or "", plan, row.notes or "", row.last_result or "")
    draft = _llm_draft(
        title=row.title or "",
        plan=plan,
        notes=row.notes or "",
        last_result=row.last_result or "",
        fallback=fallback,
    )
    local = dict(row.local_run or {})
    local["schedule_draft"] = draft.model_dump()
    row.local_run = local
    db.commit()
    return draft


def _heuristic_draft(title: str, plan: WorkflowPlan, notes: str, last_result: str) -> ScheduleDraftOut:
    name = (title or plan.title or "ИИ-агент").strip() or "ИИ-агент"
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
    low = raw.casefold()
    if any(k in low for k in ("по кнопк", "вручную", "по запрос", "из чата")):
        return None
    interval = _parse_interval(low)
    if interval is not None:
        value, unit = interval
        return ScheduleTriggerSpec(
            kind="interval",
            message=raw,
            interval_value=value,
            interval_unit=unit,
            once=False,
        )
    if re.search(r"\d{4}-\d{2}-\d{2}|\d{1,2}\.\d{1,2}\.\d{4}", raw):
        return ScheduleTriggerSpec(kind="datetime", message=raw, at=raw, once=True)
    return ScheduleTriggerSpec(kind="event", message=raw, condition=raw, once=False)


def _parse_interval(low: str) -> tuple[float, str] | None:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(минут|мин|час|дня|дней|день|сутк)", low)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit_raw = match.group(2)
    if unit_raw.startswith("мин"):
        return value, "minutes"
    if unit_raw.startswith("час"):
        return value, "hours"
    return value, "days"


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
        "- Если в материалах нет расписания — triggers: []. Тогда агент только вручную из чата.\n"
        "- Можно несколько триггеров.\n"
        "- interval — через N минут/часов/дней после последнего запуска.\n"
        "- event — условие (файл, письмо, сообщение).\n"
        "- datetime — конкретные дата и время.\n\n"
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
    condition = str(item.get("condition") or "").strip()
    at = str(item.get("at") or "").strip()
    if kind == "event" and not condition:
        return None
    if kind == "datetime" and not at:
        return None
    return ScheduleTriggerSpec(
        kind=kind,
        message=str(item.get("message") or "").strip(),
        interval_value=value,
        interval_unit=unit,
        condition=condition,
        at=at,
        once=bool(item.get("once", kind == "datetime")),
    )
