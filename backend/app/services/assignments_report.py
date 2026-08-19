"""Поручения из 1С ERP → Action Tracker / Excel с контролем статусов и артефактов."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from app.models.workflow import Workflow
from app.services.fio_utils import fio_initials_slug

_ASSIGNMENT_HINTS = (
    "поручен",
    "smart",
    "action tracker",
    "decision log",
    "критич",
    "срок",
    "формулиров",
    "отслеж",
    "артефакт",
    "статус",
)

_ACTION_TRACKER_HINTS = (
    "action tracker",
    "decision log",
    "отслеж",
    "артефакт",
    "статус исполн",
    "контроль исполн",
)

_SMART_HINTS = ("smart", "формулиров")

AssignmentsMode = Literal["smart"]

# ARGB без # — openpyxl
_FILL = {
    "overdue": "FF9B1C1C",  # тёмно-красный
    "critical": "FFE53935",  # красный
    "high": "FFFF9800",  # оранжевый
    "medium": "FFFFEB3B",  # жёлтый
    "low": "FF81C784",  # зелёный
    "unknown": "FFE0E0E0",  # серый
}

_LABEL = {
    "overdue": "Просрочено",
    "critical": "Критично (≤3 дн.)",
    "high": "Высокая (4–7 дн.)",
    "medium": "Средняя (8–14 дн.)",
    "low": "Низкая (>14 дн.)",
    "unknown": "Срок не указан",
}


_ASSIGNMENT_RUNTIME_KINDS = frozenset(
    {
        "assignments",
        "user_tasks",
        "porucheniya",
        "porucheniya_smart",
        "action_tracker",
        "onec",
    }
)

_DONE_STATUS_MARKERS = ("выполн", "закрыт", "принят", "done", "closed", "complete")
_OPEN_STATUS_MARKERS = ("открыт", "в работе", "open", "active", "нов")


def _workflow_text_blob(workflow: Workflow, *, task: str = "") -> str:
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    return " ".join(
        [
            str(workflow.title or ""),
            str(getattr(workflow, "notes", "") or ""),
            str(plan.get("title") or ""),
            str(plan.get("goal") or ""),
            str(local.get("passport_title") or ""),
            " ".join(str(x) for x in (plan.get("constraints") or [])),
            str(task or ""),
        ]
    ).casefold()


def task_implies_assignments(task: str) -> bool:
    blob = (task or "").casefold()
    return any(h in blob for h in _ASSIGNMENT_HINTS)


def is_assignments_workflow(workflow: Workflow, *, task: str = "") -> bool:
    from app.services.act_porucheniya_report import workflow_runtime_kind

    kind = workflow_runtime_kind(workflow)
    if kind in _ASSIGNMENT_RUNTIME_KINDS:
        return True
    plan = workflow.plan_json if isinstance(workflow.plan_json, dict) else {}
    plan_title = str(plan.get("title") or "").casefold()
    if any(h in plan_title for h in _ASSIGNMENT_HINTS):
        return True
    title = str(workflow.title or "").casefold()
    if any(h in title for h in _ASSIGNMENT_HINTS):
        return True
    blob = _workflow_text_blob(workflow, task=task)
    if any(h in blob for h in _ASSIGNMENT_HINTS):
        return True
    return task_implies_assignments(task)


def assignments_mode(
    workflow: Workflow,
    *,
    task: str = "",
    agent_kind: str = "",
) -> AssignmentsMode:
    """Режим агента поручений: SMART-формулировки и Excel porucheniya_*.xlsx."""
    _ = workflow, task, agent_kind
    return "smart"


def should_run_assignments_agent(
    workflow: Workflow,
    *,
    task: str = "",
    agent_kind: str = "",
) -> bool:
    from app.services.act_porucheniya_report import (
        task_implies_act_registry,
        workflow_runtime_kind,
    )

    explicit = (agent_kind or "").strip().casefold()
    if explicit in {"act_porucheniya", "act_registry"}:
        return False
    if task_implies_act_registry(task):
        return False
    if workflow_runtime_kind(workflow) in {"act_porucheniya", "act_registry"}:
        return False
    if explicit in {
        "action_tracker",
        "assignments",
        "user_tasks",
        "porucheniya",
        "porucheniya_smart",
        "onec",
    }:
        return explicit != "porucheniya" or any(
            h in (task or "").casefold() for h in _ACTION_TRACKER_HINTS
        )
    task_blob = (task or "").casefold()
    if any(h in task_blob for h in _ACTION_TRACKER_HINTS):
        return True
    if "smart" in task_blob and any(h in task_blob for h in _SMART_HINTS):
        return True
    return False


def task_implies_action_tracker(task: str) -> bool:
    blob = (task or "").casefold()
    return any(h in blob for h in _ACTION_TRACKER_HINTS) or (
        "поручен" in blob and "smart" not in blob
    )


def criticality_for_task(task: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    ref_now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    due_raw = str(task.get("due_at") or task.get("due") or "").strip()
    due = _parse_dt(due_raw)
    days_left: int | None = None
    level = "unknown"
    if due is not None:
        days_left = (due.date() - ref_now.date()).days
        if days_left < 0:
            level = "overdue"
        elif days_left <= 3:
            level = "critical"
        elif days_left <= 7:
            level = "high"
        elif days_left <= 14:
            level = "medium"
        else:
            level = "low"
    return {
        "level": level,
        "label": _LABEL[level],
        "fill": _FILL[level],
        "days_left": days_left,
    }


def _attachment_labels(task: dict[str, Any]) -> list[str]:
    raw = task.get("attachments")
    labels: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("description") or "").strip()
                if name:
                    labels.append(name)
            elif item:
                labels.append(str(item))
    return labels


def _task_is_done(status: str) -> bool:
    text = (status or "").casefold().replace(" ", "")
    if any(marker in text for marker in _DONE_STATUS_MARKERS):
        return True
    if text in {"да", "true", "1"}:
        return True
    return False


def tracking_assessment_for_task(
    task: dict[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    crit = criticality_for_task(task, now=now)
    status = str(task.get("status") or "").strip()
    if not status and _task_is_done(str(task.get("done") or "")):
        status = "выполнена"
    is_done = _task_is_done(status)
    attachments = _attachment_labels(task)
    att_count = len(attachments)
    result_text = str(task.get("result_text") or task.get("result") or "").strip()

    issues: list[str] = []
    if crit["level"] == "overdue" and not is_done:
        issues.append("просрочено, статус не закрыт")
    if is_done and att_count == 0 and not result_text:
        issues.append("отмечено выполненным без артефактов/результата")
    if crit["level"] in {"critical", "high"} and not is_done and att_count == 0:
        issues.append("срок близко, нет подтверждающих документов")
    if not is_done and att_count > 0:
        issues.append("есть материалы, статус ещё не закрыт")

    if not issues:
        state = "OK"
        fill = "FF81C784"
    elif crit["level"] == "overdue" or (is_done and att_count == 0 and not result_text):
        state = "Риск"
        fill = "FF9B1C1C"
    else:
        state = "Внимание"
        fill = "FFFF9800"

    return {
        "state": state,
        "status_label": status or ("выполнена" if is_done else "открыта"),
        "artifacts": ", ".join(attachments[:5]) if attachments else "—",
        "artifact_count": att_count,
        "result_text": result_text or "—",
        "issues": "; ".join(issues) if issues else "—",
        "fill": fill,
        "crit_label": crit["label"],
        "days_left": crit["days_left"],
    }


def build_excel_arguments(
    *,
    workflow_id: str,
    tasks: list[dict[str, Any]],
    actor_fio: str = "",
    use_llm: bool = True,
    mode: AssignmentsMode = "smart",
) -> dict[str, Any]:
    _ = mode
    return _build_smart_excel_arguments(
        workflow_id=workflow_id,
        tasks=tasks,
        actor_fio=actor_fio,
        use_llm=use_llm,
    )


def _build_smart_excel_arguments(
    *,
    workflow_id: str,
    tasks: list[dict[str, Any]],
    actor_fio: str = "",
    use_llm: bool = True,
) -> dict[str, Any]:
    headers = [
        "№",
        "Поручение",
        "Исполнитель",
        "Статус",
        "Срок",
        "Дней до срока",
        "Критичность",
        "SMART (оценка)",
        "Замечания SMART",
    ]
    rows: list[list[Any]] = []
    row_fills: list[str] = []
    smart_batch = batch_smart_for_tasks(tasks, use_llm=use_llm) if use_llm else []
    for index, task in enumerate(tasks):
        crit = criticality_for_task(task)
        if smart_batch and index < len(smart_batch):
            smart = smart_batch[index]
        else:
            smart = smart_for_task(task, has_due=crit["days_left"] is not None, use_llm=False)
        rows.append(
            [
                str(task.get("number") or ""),
                str(task.get("title") or ""),
                str(task.get("performer") or ""),
                str(task.get("status") or ""),
                str(task.get("due_at") or ""),
                "" if crit["days_left"] is None else crit["days_left"],
                crit["label"],
                smart["score"],
                smart["hint"],
            ]
        )
        row_fills.append(str(crit["fill"]))
    slug = fio_initials_slug(actor_fio, fallback="sm")
    filename = f"porucheniya_{slug}_{workflow_id[:8]}.xlsx"
    return {
        "filename": filename,
        "sheet": "Поручения",
        "headers": headers,
        "rows": rows,
        "row_fills": row_fills,
        "overwrite": True,
        "save_to_desktop": True,
        "runtime_context": {"workflow_id": workflow_id, "agent_id": workflow_id},
    }


def compose_assignments_answer(
    tasks_payload: dict[str, Any],
    excel_payload: dict[str, Any] | None,
    *,
    llm_summary: str = "",
    mode: AssignmentsMode = "smart",
) -> str:
    _ = mode
    return _compose_smart_assignments_answer(tasks_payload, excel_payload, llm_summary=llm_summary)


def _compose_smart_assignments_answer(
    tasks_payload: dict[str, Any],
    excel_payload: dict[str, Any] | None,
    *,
    llm_summary: str = "",
) -> str:
    tasks = list(tasks_payload.get("tasks") or [])
    source = str(tasks_payload.get("source") or "")
    fio = str(tasks_payload.get("fio") or "")
    lines = [
        f"Поручения 1С ({fio or 'пользователь'}): {len(tasks)} шт.",
        f"Источник данных: {source or '—'}.",
    ]
    if source == "td-docflow":
        lines.append("Раздел: Документооборот → Поручения (ТД) / задачи протоколов.")
    if source == "stub":
        lines.append(
            "⚠ ERP SQL недоступен — включите доступ к erp_pm (ERP_SQL_* в infra/.env) "
            "или проверьте VPN/сервер ii1."
        )
    if not tasks:
        com_error = str(tasks_payload.get("com_error") or "").strip()
        com_hint = str(tasks_payload.get("com_hint") or "").strip()
        if com_error:
            lines.append(f"⚠ Сервис 1С COM (:7831) недоступен: {com_error}")
            if com_hint:
                lines.append(f"→ {com_hint}")
        else:
            lines.append("Открытых поручений не найдено.")
        if llm_summary.strip():
            lines.extend(["", "Анализ LLM (SMART / приоритеты):", llm_summary.strip()])
        return "\n".join(lines)

    counts: dict[str, int] = {}
    for task in tasks:
        level = criticality_for_task(task)["level"]
        counts[level] = counts.get(level, 0) + 1
    lines.append("")
    lines.append("Критичность по срокам:")
    for key in ("overdue", "critical", "high", "medium", "low", "unknown"):
        if counts.get(key):
            lines.append(f"• {_LABEL[key]}: {counts[key]}")
    lines.append("")
    lines.append("Примеры:")
    for task in tasks[:5]:
        crit = criticality_for_task(task)
        title = str(task.get("title") or "—")[:80]
        lines.append(f"• [{crit['label']}] {title}")
    if excel_payload and excel_payload.get("path"):
        desktop = excel_payload.get("desktop_path") or excel_payload.get("path")
        lines.extend(
            [
                "",
                f"Excel с цветовой индикацией: {desktop}",
                "Легенда: красный — срочно/просрочено, оранжевый — 4–7 дн., "
                "жёлтый — 8–14 дн., зелёный — >14 дн., серый — без срока.",
            ]
        )
    if llm_summary.strip():
        lines.extend(["", "Анализ LLM (SMART / приоритеты):", llm_summary.strip()])
    return "\n".join(lines)


def smart_for_task(
    task: dict[str, Any],
    *,
    has_due: bool,
    use_llm: bool = True,
) -> dict[str, Any]:
    title = str(task.get("title") or "")
    if use_llm:
        llm_result = _smart_with_llm(title, has_due=has_due)
        if llm_result is not None:
            return llm_result
    return _smart_flags(title, has_due)


def batch_smart_for_tasks(
    tasks: list[dict[str, Any]],
    *,
    use_llm: bool = True,
) -> list[dict[str, Any]]:
    if not use_llm or not tasks:
        return []
    from app.services.llm_provider import effective_llm_provider, llm_ready

    if not llm_ready():
        return []
    if effective_llm_provider() == "cursor":
        return _batch_smart_with_llm(tasks)
    return [
        smart_for_task(
            task,
            has_due=bool(str(task.get("due_at") or task.get("due") or "").strip()),
            use_llm=True,
        )
        for task in tasks
    ]


def _batch_smart_with_llm(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.services import runtime_llm

    lines = []
    for index, task in enumerate(tasks[:30], start=1):
        title = str(task.get("title") or "—")
        due = str(task.get("due_at") or task.get("due") or "—")
        lines.append(f"{index}. [{due}] {title}")
    prompt = (
        "Оцени формулировки поручений по SMART. "
        "Верни JSON-массив той же длины и порядка: "
        '[{"score":"0-100%","flags":"S+M+T","hint":"кратко на русском"}].\n\n'
        + "\n".join(lines)
    )
    raw = runtime_llm.generate(
        prompt,
        system=(
            "Помощник ПСД. Только валидный JSON-массив без markdown и пояснений."
        ),
        max_tokens=2048,
        quick=False,
    )
    if not raw:
        return []
    import json
    import re

    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            out.append(_smart_flags("", False))
            continue
        out.append(
            {
                "score": str(item.get("score") or "—"),
                "flags": str(item.get("flags") or "—"),
                "hint": str(item.get("hint") or "—"),
            }
        )
    return out


def _smart_with_llm(title: str, *, has_due: bool) -> dict[str, Any] | None:
    from app.services.llm_provider import llm_ready
    from app.services import runtime_llm

    if not llm_ready() or not title.strip():
        return None

    prompt = (
        "Проверь формулировку поручения по критериям SMART (Specific, Measurable, "
        "Achievable, Relevant, Time-bound). "
        f"Срок в 1С указан: {'да' if has_due else 'нет'}.\n"
        f"Поручение: {title}\n\n"
        "Ответь одной строкой JSON без markdown: "
        '{"score":"0-100%","flags":"S+M+T","hint":"краткая рекомендация на русском"}'
    )
    raw = runtime_llm.generate(
        prompt,
        system=(
            "Ты помощник председателя совета директоров. Оценивай поручения строго "
            "по регламенту SMART. Только валидный JSON в ответе."
        ),
        max_tokens=256,
        quick=True,
    )
    if not raw:
        return None
    import json
    import re

    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    score = str(data.get("score") or "—")
    flags = str(data.get("flags") or "—")
    hint = str(data.get("hint") or "—")
    return {"score": score, "flags": flags, "hint": hint}


def compose_llm_assignments_summary(
    tasks: list[dict[str, Any]],
    *,
    mode: AssignmentsMode = "smart",
) -> str:
    _ = mode
    return _compose_llm_smart_summary(tasks)


def compose_llm_tracking_summary(tasks: list[dict[str, Any]]) -> str:
    from app.services.llm_provider import llm_ready
    from app.services import runtime_llm

    if not llm_ready() or not tasks:
        return ""

    lines = []
    for task in tasks[:12]:
        track = tracking_assessment_for_task(task)
        lines.append(
            f"- [{track['state']}] {str(task.get('title') or '')[:120]} "
            f"(статус: {track['status_label']}, срок: {task.get('due_at') or '—'}, "
            f"артефакты: {track['artifact_count']}, проблемы: {track['issues']})"
        )
    prompt = (
        "Кратко (до 8 предложений) проанализируй поручения как Action Tracker: "
        "где просрочка, где нет артефактов/результата, что эскалировать.\n\n"
        + "\n".join(lines)
    )
    reply = runtime_llm.generate(
        prompt,
        system="Помощник Action Tracker / Decision Log. Русский язык, деловой стиль, без markdown.",
        max_tokens=512,
    )
    return (reply or "").strip()


def _compose_llm_smart_summary(tasks: list[dict[str, Any]]) -> str:
    from app.services.llm_provider import llm_ready
    from app.services import runtime_llm

    if not llm_ready() or not tasks:
        return ""

    lines = []
    for task in tasks[:12]:
        crit = criticality_for_task(task)
        lines.append(
            f"- [{crit['label']}] {str(task.get('title') or '')[:120]} "
            f"(срок: {task.get('due_at') or '—'})"
        )
    prompt = (
        "Кратко (до 8 предложений) проанализируй список поручений: "
        "что срочно, где нарушен SMART, что эскалировать.\n\n"
        + "\n".join(lines)
    )
    reply = runtime_llm.generate(
        prompt,
        system="Помощник ПСД. Русский язык, деловой стиль, без markdown.",
        max_tokens=512,
    )
    return (reply or "").strip()


def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def _smart_flags(title: str, has_due: bool) -> dict[str, Any]:
    """Эвристика SMART без LLM (Specific / Measurable / Time-bound)."""
    text = (title or "").strip()
    words = len(text.split())
    flags: list[str] = []
    score = 0
    if words >= 5:
        flags.append("S")
        score += 25
    if any(ch.isdigit() for ch in text):
        flags.append("M")
        score += 25
    if has_due:
        flags.append("T")
        score += 25
    if words >= 12:
        flags.append("A/R")
        score += 25
    hints: list[str] = []
    if "S" not in flags:
        hints.append("уточнить формулировку (коротко/размыто)")
    if "M" not in flags:
        hints.append("нет измеримого результата")
    if "T" not in flags:
        hints.append("нет срока в 1С")
    if "A/R" not in flags:
        hints.append("возможно неполная формулировка")
    hint = "; ".join(hints) if hints else "формулировка базово SMART"
    return {"score": f"{score}%", "flags": "+".join(flags) or "—", "hint": hint}
