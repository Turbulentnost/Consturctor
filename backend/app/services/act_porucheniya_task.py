"""Разбор задачи пользователя для фильтрации ACT-реестра и контекста вложений."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.act_porucheniya_report import criticality_for_deadline
from app.services.fio_utils import fio_initials_slug

_ACT_NUM_RE = re.compile(
    r"(?:ACT|АСТ)\s*00\s*-\s*(\d+)(?!\*)",
    re.IGNORECASE,
)
_EXCEL_PATH_RE = re.compile(
    r"(?:file:///)?(?P<path>[A-Za-z]:[\\/](?:[^\\/\s\"']+[\\/])*[^\\/\s\"']+\.xlsx)",
    re.IGNORECASE,
)
_EXCEL_NAME_RE = re.compile(r"([\w\-]+\.xlsx)", re.IGNORECASE)

_SUMMARIZE_HINTS = (
    "суммир",
    "суммар",
    "summar",
    "сводк",
    "проанализ",
    "расскаж",
    "что в файле",
    "что в excel",
    "из этого excel",
    "из файла",
    "из этого xlsx",
    "прочитай excel",
    "по файлу",
    "из excel",
    "информаци",
    "опиши файл",
    "разбери файл",
)
_EXPORT_HINTS = (
    "выгруз",
    "создай excel",
    "полный реестр",
    "реестр из odata",
    "через odata",
    "document_тд",
    "на рабочий стол",
    "act-реестр",
    "act реестр",
)
_REFORMAT_HINTS = (
    "обнови excel",
    "пересоздай excel",
    "перегенер",
    "перезапиши excel",
    "перекрас",
    "обнови цвет",
    "новая палитр",
    "светл",
    "цвет",
    "палитр",
    "перекрась",
    "сделай цвет",
)
_CHAT_HINTS = (
    "без excel",
    "без файла",
    "только сводк",
    "не создавай excel",
    "в чате",
    "ответь",
    "сколько",
    "покажи",
    "найди",
    "фильтр",
    "просроч",
    "кто исполн",
)
_MERGE_ADD_HINTS = (
    "добавь",
    "дополни",
    "дополн",
    "из протокола",
    "по протоколу",
    "новая задача",
    "внеси в реестр",
    "внеси задачу",
    "протокол",
)

_STATUS_HINTS: dict[str, tuple[str, ...]] = {
    "accepted": ("принят", "accepted"),
    "in_progress": ("в работе", "in progress", "вработе"),
    "created": ("создан", "new", "нов"),
    "done": ("done", "выполн", "заверш"),
}


def act_desktop_excel_candidates(*, actor_fio: str, workflow_id: str) -> list[str]:
    """Имена Excel на рабочем столе: точное для workflow, затем маска по инициалам."""
    slug = fio_initials_slug(actor_fio, fallback="act")
    return [
        f"act_porucheniya_{slug}_{workflow_id[:8]}.xlsx",
        f"act_porucheniya_{slug}_*.xlsx",
    ]


def extract_act_numbers(task: str) -> list[str]:
    """Номера ACT из текста задачи, нормализованные как ACT00-00088."""
    found: list[str] = []
    for match in _ACT_NUM_RE.finditer(task or ""):
        num = int(match.group(1))
        if num <= 0:
            continue
        normalized = f"ACT00-{num:05d}"
        if normalized not in found:
            found.append(normalized)
    return found


def extract_excel_path_from_task(task: str) -> str:
    """Путь или имя .xlsx из задачи (file:///C:/… или C:\\…)."""
    text = task or ""
    match = _EXCEL_PATH_RE.search(text.replace("\\", "/"))
    if match:
        return match.group("path").replace("/", "\\")
    for token in text.split():
        cleaned = token.strip("\"'(),;")
        if cleaned.lower().startswith("file:"):
            parsed = urlparse(cleaned)
            raw = unquote(parsed.path or "")
            if raw.startswith("/") and len(raw) > 2 and raw[2] == ":":
                raw = raw[1:]
            if raw.lower().endswith(".xlsx"):
                return raw.replace("/", "\\")
        if cleaned.lower().endswith(".xlsx"):
            return cleaned
    name_match = _EXCEL_NAME_RE.search(text)
    if name_match and "act_porucheniya" in text.casefold():
        return name_match.group(1)
    return ""


def task_implies_full_odata_export(task: str) -> bool:
    blob = (task or "").casefold()
    return any(h in blob for h in _EXPORT_HINTS)


def task_implies_reformat_excel(task: str) -> bool:
    blob = (task or "").casefold()
    return any(h in blob for h in _REFORMAT_HINTS)


def task_implies_act_registry_action(task: str) -> bool:
    """Есть ли в сообщении команда/вопрос по ACT-реестру (не произвольный чат)."""
    blob = (task or "").casefold().strip()
    if not blob:
        return True

    from app.services.act_porucheniya_report import task_implies_act_registry
    from app.services.act_protocol_merge import (
        looks_like_inline_task_addition,
        task_implies_protocol_merge,
    )

    if extract_act_numbers(task) or extract_excel_path_from_task(task):
        return True
    if looks_like_inline_task_addition(task) or task_implies_protocol_merge(task):
        return True
    if task_implies_act_registry(task):
        return True
    if task_implies_full_odata_export(task) or task_implies_reformat_excel(task):
        return True
    domain_hints = _CHAT_HINTS + _SUMMARIZE_HINTS + _MERGE_ADD_HINTS + (
        "excel",
        "xlsx",
        "odata",
        "1с",
        "поруч",
        "реестр",
        "задача:",
        "исполнитель:",
        "act",
        "аст",
        "протокол",
        "срок до",
    )
    return any(h in blob for h in domain_hints)


def parse_act_task_intent(task: str) -> str:
    """export | reformat_excel | merge_add | summarize_excel | analyze_chat | freeform_chat."""
    blob = (task or "").casefold().strip()
    if not blob:
        return "export"

    from app.services.act_protocol_merge import (
        looks_like_inline_task_addition,
        task_implies_protocol_merge,
    )

    excel_path = extract_excel_path_from_task(task)
    wants_summary = any(h in blob for h in _SUMMARIZE_HINTS)
    wants_export = task_implies_full_odata_export(task)
    wants_reformat = task_implies_reformat_excel(task)

    if excel_path and wants_reformat and not wants_summary:
        return "reformat_excel"
    if excel_path:
        if wants_export and not wants_summary:
            return "export"
        return "summarize_excel"
    if looks_like_inline_task_addition(task) or (
        task_implies_protocol_merge(task) and not wants_export and not wants_reformat
    ):
        return "merge_add"
    if wants_reformat and not wants_summary:
        return "reformat_excel"
    if wants_export and not wants_summary:
        return "export"
    if any(h in blob for h in _CHAT_HINTS):
        return "analyze_chat"
    if extract_act_numbers(task) or any(h in blob for h in ("act00", "аст00", "номер act")):
        return "analyze_chat"
    if not task_implies_act_registry_action(task):
        return "freeform_chat"
    return "analyze_chat"


def parse_act_filter_from_task(task: str) -> dict[str, Any]:
    """Эвристики фильтра из чата — без LLM."""
    blob = (task or "").casefold()
    from app.services.act_protocol_merge import (
        looks_like_inline_task_addition,
        task_implies_protocol_merge,
    )

    filt: dict[str, Any] = {
        "act_numbers": extract_act_numbers(task or ""),
        "criticality_levels": [],
        "status_keys": [],
        "keywords": [],
        "only_open": False,
        "refresh_excel": True,
    }

    merge_or_add = looks_like_inline_task_addition(task) or task_implies_protocol_merge(task)
    explicit_filter = any(
        x in blob for x in ("только просроч", "только критич", "покажи только", "фильтр")
    )
    if merge_or_add and not explicit_filter:
        filt["act_numbers"] = []
        return filt

    if any(x in blob for x in ("просроч", "overdue", "истек")):
        filt["criticality_levels"].append("overdue")
    if any(x in blob for x in ("критич", "≤3", "3 дн", "3 дня", "срочн")):
        filt["criticality_levels"].append("critical")
    if "высок" in blob or "4-7" in blob or "4–7" in blob:
        filt["criticality_levels"].append("high")
    if "средн" in blob or "8-14" in blob or "8–14" in blob:
        filt["criticality_levels"].append("medium")
    if any(x in blob for x in ("низк", "зелен", "зелён")):
        filt["criticality_levels"].append("low")

    if any(x in blob for x in ("принят", "accepted", "закрыт", "closed")):
        filt["status_keys"].append("accepted")
    if re.search(r"(?:только|покажи|фильтр|where).{0,40}(?:в работе|in progress)", blob):
        filt["status_keys"].append("in_progress")
        filt["only_open"] = True
    elif re.search(r"статус\s*(?::|\s+)\s*(?:в\s*)?работ", blob) and explicit_filter:
        filt["status_keys"].append("in_progress")
        filt["only_open"] = True
    if re.search(r"(?:только|покажи|фильтр).{0,40}создан", blob) or re.search(
        r"статус\s*:\s*создан", blob
    ):
        filt["status_keys"].append("created")

    if explicit_filter:
        filt["only_open"] = filt["only_open"] or bool(filt["criticality_levels"])

    if any(x in blob for x in ("без excel", "без файла", "только сводк", "не создавай excel")):
        filt["refresh_excel"] = False

    if task_implies_full_odata_export(task) or task_implies_reformat_excel(task):
        filt["refresh_excel"] = True
    elif parse_act_task_intent(task) in {"summarize_excel", "analyze_chat", "freeform_chat"}:
        filt["refresh_excel"] = False

    # ключевые слова в «О чём» — фраза в кавычках или после «где»/«про»
    for m in re.finditer(r"[«\"']([^»\"']{3,80})[»\"']", task or ""):
        filt["keywords"].append(m.group(1).casefold())

    return filt


def _status_key(status: str) -> str:
    text = (status or "").casefold().replace(" ", "")
    if text.startswith("принят"):
        return "accepted"
    if "работ" in text:
        return "in_progress"
    if "создан" in text:
        return "created"
    if "выполн" in text or "done" in text:
        return "done"
    return "other"


def apply_act_document_filters(
    documents: list[dict[str, Any]],
    filt: dict[str, Any],
) -> tuple[list[dict[str, Any]], str]:
    """Отфильтровать документы и строки task_lines; вернуть (список, описание)."""
    if not documents:
        return [], "нет данных"

    result = list(documents)
    parts: list[str] = []

    numbers = list(filt.get("act_numbers") or [])
    if numbers:
        nums_upper = {n.upper() for n in numbers}
        result = [
            d
            for d in result
            if str(d.get("number_display") or d.get("number") or "").upper().replace("АСТ", "ACT")
            in nums_upper
            or any(n in str(d.get("number") or "").upper().replace("АСТ", "ACT") for n in nums_upper)
        ]
        parts.append(f"номера: {', '.join(numbers)}")

    status_keys = list(filt.get("status_keys") or [])
    if status_keys:
        allowed = set(status_keys)
        result = [d for d in result if _status_key(str(d.get("status") or "")) in allowed]
        parts.append(f"статус: {', '.join(status_keys)}")

    keywords = list(filt.get("keywords") or [])
    for kw in keywords:
        if not kw:
            continue
        result = [
            d
            for d in result
            if kw in str(d.get("about") or d.get("activity_summary") or "").casefold()
            or kw in str(d.get("basis") or "").casefold()
            or any(kw in str(line.get("task") or "").casefold() for line in (d.get("task_lines") or []))
        ]
        parts.append(f"ключ: «{kw}»")

    if filt.get("only_open") and not status_keys:
        result = [d for d in result if _status_key(str(d.get("status") or "")) != "accepted"]
        parts.append("без принятых")

    levels = list(filt.get("criticality_levels") or [])
    if levels:
        level_set = set(levels)
        for doc in result:
            lines = [
                line
                for line in (doc.get("task_lines") or [])
                if criticality_for_deadline(str(line.get("deadline_raw") or ""))["level"] in level_set
            ]
            doc["task_lines"] = lines
            doc["task_line_count"] = len(lines)
        result = [d for d in result if d.get("task_lines")]
        parts.append(f"критичность задачи: {', '.join(levels)}")

    desc = "; ".join(parts) if parts else "без фильтров (полный реестр)"
    return result, desc


def workflow_attachment_context(workflow: Any) -> str:
    """Краткий контекст из notes/document_text workflow для LLM."""
    chunks: list[str] = []
    notes = str(getattr(workflow, "notes", "") or "").strip()
    doc = str(getattr(workflow, "document_text", "") or "").strip()
    if notes and notes not in doc:
        chunks.append(notes[:1500])
    if doc:
        chunks.append(doc[:2500])
    return "\n\n".join(chunks).strip()
