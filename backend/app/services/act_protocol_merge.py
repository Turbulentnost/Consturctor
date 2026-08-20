"""Разбор протокола совещания и слияние новых ACT-задач с OData-реестром."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.act_porucheniya_odata import normalize_act_number

_ACT_HEADER_RE = re.compile(
    r"^(?:ACT|АСТ)\s*0*-?\s*0*(\d+)\s*[—\-–]\s*[«\"']?(.+?)[»\"']?\s*$",
    re.IGNORECASE,
)
_TASK_NUM_RE = re.compile(r"^\s*(\d+)\.\s+(.+)$")
_EXECUTOR_RE = re.compile(r"^\s*Исполнитель:\s*(.+?)\s*$", re.IGNORECASE)
_DEADLINE_RE = re.compile(r"^\s*Срок:\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*$", re.IGNORECASE)
_STATUS_RE = re.compile(r"Статус:\s*([^|]+)", re.IGNORECASE)
_REPORTER_RE = re.compile(r"Кто\s+доложит:\s*([^|]+)", re.IGNORECASE)
_PROTOCOL_DATE_RE = re.compile(r"^\s*Дата:\s*(\d{1,2}\.\d{1,2}\.\d{4})\s*$", re.IGNORECASE)
_FREEFORM_SKIP_RE = re.compile(
    r"^(?:ПРОТОКОЛ|Дата:|Участники:|Кратко:|Секретарь:|Подпись:)",
    re.IGNORECASE,
)
_PROTOCOL_MARKERS = ("--- протокол ---", "---протокол---", "протокол совещания", "новые поручения")
_MERGE_HINTS = (
    "дополни",
    "дополн",
    "добавь",
    "добавь ещё",
    "добавь еще",
    "из протокола",
    "по протоколу",
    "новый act",
    "новые act",
    "новое поручение",
    "новая задача",
    "внеси в реестр",
    "внеси задачу",
    "merge",
    "протокол",
)
_INLINE_TASK_RE = re.compile(
    r"задача\s*:\s*(.+?)\s*,\s*исполнитель\s*:\s*(.+?)\s*,\s*"
    r"срок\s*до\s*(\d{1,2}\.\d{1,2}\.\d{2,4})"
    r"(?:\s*,\s*статус\s*(?::|\s+)\s*(.+))?$",
    re.IGNORECASE,
)
_STRUCTURED_ADD_RE = re.compile(
    r"исполнитель\s*[—:\-]\s*(?P<executor>.+?)\s*,\s*"
    r"срок\s*(?P<deadline>\d{1,2}\.\d{1,2}\.\d{2,4})\s*,\s*"
    r"задача\s*[—:\-]\s*[\"«']?(?P<task>.+?)(?:[\"»']|\)|\.(?=\s)|$)",
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)
_RECORD_ADD_RE = re.compile(
    r"добав(?:ь|ить|лю|ля(?:й|те)?)"
    r".*?"
    r"запис(?:ь|и)?"
    r"\s+"
    r"(?P<executor>(?:[А-ЯЁA-Z][а-яёa-z\-]+(?:\s+|-)?){1,4})"
    r"\s+"
    r"(?P<deadline>\d{1,2}\.\d{1,2}\.\d{2,4})"
    r"\s+"
    r"(?P<task>.+?)\s*$",
    re.IGNORECASE | re.UNICODE | re.DOTALL,
)


def looks_like_inline_task_addition(task: str) -> bool:
    return bool(_INLINE_TASK_RE.search(task or ""))


def looks_like_record_addition(task: str) -> bool:
    """«добавь … запись Иванов И.И. 29.09.26 Текст задачи» или structured add."""
    return bool(_RECORD_ADD_RE.search(task or "") or _STRUCTURED_ADD_RE.search(task or ""))


def task_implies_protocol_merge(task: str) -> bool:
    blob = (task or "").casefold()
    if looks_like_inline_task_addition(task) or looks_like_record_addition(task):
        return True
    if any(m in blob for m in _MERGE_HINTS):
        return True
    return any(m in blob for m in _PROTOCOL_MARKERS)


def _looks_like_freeform_protocol(text: str) -> bool:
    blob = (text or "").strip()
    if not blob:
        return False
    if _ACT_HEADER_RE.search(blob):
        return False
    lowered = blob.casefold()
    if "исполнитель:" not in lowered or "срок:" not in lowered:
        return False
    return any(token in lowered for token in ("протокол", "поручен", "совещан"))


def extract_protocol_text(task: str, *, workflow_text: str = "") -> str:
    """Текст протокола из задачи (блок после --- ПРОТОКОЛ ---) или workflow."""
    task = task or ""
    if looks_like_inline_task_addition(task) or looks_like_record_addition(task):
        return task
    for marker in ("--- ПРОТОКОЛ ---", "---ПРОТОКОЛ---", "--- протокол ---"):
        if marker.casefold() in task.casefold():
            idx = task.casefold().index(marker.casefold())
            tail = task[idx + len(marker) :].strip()
            if tail:
                return tail
    if task_implies_protocol_merge(task) and _ACT_HEADER_RE.search(task):
        return task
    if task_implies_protocol_merge(task) and _looks_like_freeform_protocol(task):
        return task
    wt = (workflow_text or "").strip()
    if wt and _ACT_HEADER_RE.search(wt) and ("протокол" in wt.casefold() or "поручен" in wt.casefold()):
        return wt
    if task_implies_protocol_merge(task) and _looks_like_freeform_protocol(wt):
        return wt
    return ""


def _deadline_raw_from_display(display: str) -> str:
    text = (display or "").strip()
    if not text:
        return ""
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%Y-%m-%dT00:00:00")
        except ValueError:
            continue
    return ""


def _protocol_number_from_date(date_display: str) -> str:
    text = (date_display or "").strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            dt = datetime.strptime(text, fmt)
            return f"ACT00-PROTO-{dt.strftime('%Y%m%d')}"
        except ValueError:
            continue
    return "ACT00-PROTO-UNKNOWN"


def _normalize_short_year_deadline(display: str) -> str:
    text = (display or "").strip()
    for fmt in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            continue
    return text


def _document_from_chat_task(
    *,
    task_text: str,
    executor: str,
    deadline: str,
    status: str = "В работе",
    number_display: str = "",
    about: str = "",
) -> dict[str, Any]:
    deadline = _normalize_short_year_deadline(deadline)
    act = number_display or _protocol_number_from_date(deadline)
    return {
        "number": act,
        "number_display": act,
        "about": about or f"Добавлено из чата ({deadline})",
        "status": status or "В работе",
        "reporter": "",
        "secretary": "",
        "task_lines": [
            {
                "line_number": 1,
                "task": task_text.strip().rstrip(","),
                "executor": executor.strip().rstrip(","),
                "deadline": deadline,
                "deadline_raw": _deadline_raw_from_display(deadline),
                "priority": "",
                "source": "protocol",
            }
        ],
        "task_line_count": 1,
        "source": "protocol",
    }


def _parse_structured_addition(text: str) -> list[dict[str, Any]]:
    match = _STRUCTURED_ADD_RE.search(text or "")
    if not match:
        return []
    return [
        _document_from_chat_task(
            task_text=match.group("task").strip().strip("«»\"'"),
            executor=match.group("executor").strip(),
            deadline=match.group("deadline").strip(),
        )
    ]


def _parse_record_addition(text: str) -> list[dict[str, Any]]:
    """«добавь … запись ФИО DD.MM.YY текст задачи»."""
    structured = _parse_structured_addition(text)
    if structured:
        return structured
    match = _RECORD_ADD_RE.search(text or "")
    if not match:
        return []
    executor = re.sub(r"\s+", " ", match.group("executor").strip())
    deadline = match.group("deadline").strip()
    task_text = match.group("task").strip().rstrip(",")
    if not executor or not deadline or not task_text:
        return []
    return [
        _document_from_chat_task(
            task_text=task_text,
            executor=executor,
            deadline=deadline,
        )
    ]


def _parse_inline_task_addition(text: str) -> list[dict[str, Any]]:
    """Одна задача в чате: «Задача: …, Исполнитель: …, срок до DD.MM.YY»."""
    match = _INLINE_TASK_RE.search(text or "")
    if not match:
        return []

    task_text = match.group(1).strip().rstrip(",")
    executor = match.group(2).strip().rstrip(",")
    deadline = _normalize_short_year_deadline(match.group(3).strip())
    status = (match.group(4) or "В работе").strip().rstrip(",") or "В работе"
    return [
        _document_from_chat_task(
            task_text=task_text,
            executor=executor,
            deadline=deadline,
            status=status,
        )
    ]


def _parse_freeform_protocol(protocol_text: str) -> list[dict[str, Any]]:
    """Свободный протокол: блоки «задача / Исполнитель / Срок» без ACT00-***."""
    if not (protocol_text or "").strip():
        return []

    protocol_date = ""
    title = "Протокол совещания"
    for raw_line in protocol_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        date_match = _PROTOCOL_DATE_RE.match(line)
        if date_match:
            protocol_date = date_match.group(1).strip()
            continue
        if line.casefold().startswith("протокол"):
            title = line
            continue

    blocks = re.split(r"^\s*---+\s*$", protocol_text, flags=re.MULTILINE)
    task_lines: list[dict[str, Any]] = []

    for block in blocks:
        task_parts: list[str] = []
        executor = ""
        deadline = ""
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if not line or _FREEFORM_SKIP_RE.match(line):
                continue
            ex = _EXECUTOR_RE.match(line)
            if ex:
                executor = ex.group(1).strip()
                continue
            dl = _DEADLINE_RE.match(line)
            if dl:
                deadline = dl.group(1).strip()
                continue
            if executor or deadline:
                continue
            task_parts.append(line)

        task = " ".join(task_parts).strip()
        if not task or not executor:
            continue
        task_lines.append(
            {
                "line_number": len(task_lines) + 1,
                "task": task,
                "executor": executor,
                "deadline": deadline,
                "deadline_raw": _deadline_raw_from_display(deadline),
                "priority": "",
                "source": "protocol",
            }
        )

    if not task_lines:
        return []

    number_display = _protocol_number_from_date(protocol_date)
    about = title
    if protocol_date and protocol_date not in about:
        about = f"{title} ({protocol_date})"

    return [
        {
            "number": number_display,
            "number_display": number_display,
            "about": about,
            "status": "В работе",
            "reporter": "",
            "secretary": "",
            "task_lines": task_lines,
            "task_line_count": len(task_lines),
            "source": "protocol",
        }
    ]


def parse_protocol_to_documents(protocol_text: str) -> list[dict[str, Any]]:
    """Протокол → список документов с task_lines (как OData)."""
    if not (protocol_text or "").strip():
        return []

    record_add = _parse_record_addition(protocol_text)
    if record_add:
        return record_add

    inline = _parse_inline_task_addition(protocol_text)
    if inline:
        return inline

    documents: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    pending_task: dict[str, Any] | None = None

    def flush_task() -> None:
        nonlocal pending_task
        if current is not None and pending_task and pending_task.get("task"):
            current.setdefault("task_lines", []).append(pending_task)
        pending_task = None

    def flush_doc() -> None:
        nonlocal current
        flush_task()
        if current is not None and (current.get("task_lines") or current.get("about")):
            current["task_line_count"] = len(current.get("task_lines") or [])
            current["source"] = "protocol"
            documents.append(current)
        current = None

    for raw_line in protocol_text.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue

        header = _ACT_HEADER_RE.match(line.strip())
        if header:
            flush_doc()
            num = int(header.group(1))
            about = header.group(2).strip().strip("«»\"'")
            number_display = f"ACT00-{num:05d}"
            current = {
                "number": number_display,
                "number_display": number_display,
                "about": about,
                "status": "",
                "reporter": "",
                "secretary": "",
                "task_lines": [],
                "source": "protocol",
            }
            continue

        if current is None:
            continue

        task_match = _TASK_NUM_RE.match(line)
        if task_match:
            flush_task()
            pending_task = {
                "line_number": int(task_match.group(1)),
                "task": task_match.group(2).strip(),
                "executor": "",
                "deadline": "",
                "deadline_raw": "",
                "priority": "",
                "source": "protocol",
            }
            continue

        if pending_task is not None:
            ex = _EXECUTOR_RE.match(line)
            if ex:
                pending_task["executor"] = ex.group(1).strip()
                continue
            dl = _DEADLINE_RE.match(line)
            if dl:
                pending_task["deadline"] = dl.group(1).strip()
                pending_task["deadline_raw"] = _deadline_raw_from_display(dl.group(1))
                continue

        st = _STATUS_RE.search(line)
        if st and current is not None:
            current["status"] = st.group(1).strip()
        rep = _REPORTER_RE.search(line)
        if rep and current is not None:
            current["reporter"] = rep.group(1).strip()

    flush_doc()
    if documents:
        return documents
    return _parse_freeform_protocol(protocol_text)


def _task_key(task: str) -> str:
    return re.sub(r"\s+", " ", (task or "").casefold()).strip()[:120]


def merge_protocol_documents(
    odata_documents: list[dict[str, Any]],
    protocol_documents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Добавить/дополнить документы из протокола (не перезаписывая OData)."""
    by_number: dict[str, dict[str, Any]] = {}
    for doc in odata_documents:
        key = normalize_act_number(str(doc.get("number_display") or doc.get("number") or "")).upper()
        if key:
            by_number[key] = doc

    added_docs = 0
    added_lines = 0
    skipped_lines = 0

    for pdoc in protocol_documents:
        key = normalize_act_number(str(pdoc.get("number_display") or "")).upper()
        if not key:
            continue
        existing = by_number.get(key)
        if existing is None:
            by_number[key] = pdoc
            odata_documents.append(pdoc)
            added_docs += 1
            added_lines += len(pdoc.get("task_lines") or [])
            continue

        existing_keys = {
            _task_key(str(line.get("task") or ""))
            for line in (existing.get("task_lines") or [])
        }
        for line in pdoc.get("task_lines") or []:
            tk = _task_key(str(line.get("task") or ""))
            if not tk or tk in existing_keys:
                skipped_lines += 1
                continue
            marked = dict(line)
            marked["source"] = "protocol"
            existing.setdefault("task_lines", []).append(marked)
            existing_keys.add(tk)
            added_lines += 1
        if not str(existing.get("status") or "").strip() and pdoc.get("status"):
            existing["status"] = pdoc["status"]
        existing["task_line_count"] = len(existing.get("task_lines") or [])

    stats = {
        "protocol_documents": len(protocol_documents),
        "added_documents": added_docs,
        "added_task_lines": added_lines,
        "skipped_duplicate_lines": skipped_lines,
    }
    return odata_documents, stats
