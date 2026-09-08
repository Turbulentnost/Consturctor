from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_PROMPT_ATTACHMENT_CHARS = 120_000

_UNKNOWN_VALUES = {
    "",
    "-",
    "нет",
    "не указано",
    "неизвестно",
    "нет данных",
    "n/a",
    "none",
    "null",
    "пока неизвестно",
}

_FIELD_ALIASES = {
    "tool": ("tool", "instrument", "system", "tools", "systems", "инструмент", "система"),
    "periodicity": (
        "periodicity",
        "frequency",
        "cadence",
        "schedule",
        "howOften",
        "как часто",
        "периодичность",
    ),
    "triggerAction": (
        "triggerAction",
        "trigger",
        "startEvent",
        "start_event",
        "condition",
        "event",
        "триггер",
        "условие запуска",
    ),
    "userAction": (
        "userAction",
        "howUserDoes",
        "humanAction",
        "actionDetails",
        "как пользователь делает",
        "действие пользователя",
    ),
}

_VAGUE_TRIGGER_PATTERNS = [
    r"\bпо мере необходимости\b",
    r"\bпри необходимости\b",
    r"\bсвоевременно\b",
    r"\bзаблаговременно\b",
    r"\bконтрол",
    r"\bобеспеч",
    r"\bотслеж",
    r"\bнапом",
    r"\bуведом",
    r"\bпроинформ",
    r"\bсообщ",
    r"\bза\s+\d+\s*(?:час|ч\.|минут|мин\.|дн)",
]

_CONCRETE_ACTION_MARKERS = [
    "outlook",
    "почт",
    "письм",
    "1с",
    "1c",
    "excel",
    "word",
    "telegram",
    "teams",
    "чат",
    "звон",
    "телефон",
    "папк",
    "файл",
    "карточ",
    "статус",
    "заявк",
    "созда",
    "получ",
    "приход",
    "появ",
    "отправ",
    "откры",
    "сохраня",
    "заполня",
    "выгружа",
    "загружа",
    "наступ",
]

_DOCUMENT_FIELD_LABELS = (
    "основание",
    "исполнитель",
    "инструмент",
    "периодичность",
    "триггер",
    "действие пользователя",
    "источник",
)

_DOCUMENT_SERVICE_PREFIXES = (
    "основание",
    "предположение",
)


@dataclass(slots=True)
class ReadyBlocker:
    message: str
    quick_answers: list[str]
    function_id: str = ""
    field: str = ""


ROLE_BELONGS = "belongs"
ROLE_FOREIGN = "foreign"
ROLE_UNCLEAR = "unclear"

_GENERIC_ACTORS = {
    "подразделение",
    "ответственные",
    "ответственный",
    "сотрудник",
    "сотрудники",
    "работник",
    "исполнитель",
    "пользователь",
    "специалист",
    "команда",
    "отдел",
    "все",
}

_ROLE_BELONGS_MARKERS = (
    "да, это моя",
    "это моя обязанность",
    "моя обязанность",
    "относится к моей",
    "да, относится",
)
_ROLE_FOREIGN_MARKERS = (
    "нет, другая",
    "другая роль",
    "не относится",
    "не моя",
    "не мой",
    "чужая роль",
    "снимаю",
    "снимите",
    "не моя обязанность",
    "не мой процесс",
)

_ANSWER_SUFFICIENCY_STATUSES = {"closed", "partial", "not_answered"}

_PROCESS_FACT_ALIASES = {
    "inputs": ("inputs", "input", "sourceInputs", "входы", "исходные данные", "что поступает"),
    "workLocation": (
        "workLocation",
        "dataSources",
        "readWriteSources",
        "tool",
        "instrument",
        "system",
        "channel",
        "place",
        "location",
        "где работает",
        "место работы",
        "система",
        "источник данных",
        "источники чтения",
        "чтение и запись",
    ),
    "objects": ("objects", "records", "forms", "registers", "entities", "объекты", "реестры", "формы"),
    "trigger": ("trigger", "triggerAction", "startEvent", "condition", "триггер", "условие запуска"),
    "deadlines": (
        "deadlines",
        "deadline",
        "dueDate",
        "timing",
        "срок",
        "сроки",
        "сроки выполнения",
        "к какому сроку",
    ),
    "frequency": ("frequency", "periodicity", "cadence", "schedule", "периодичность", "как часто"),
    "steps": ("steps", "actions", "userAction", "procedure", "шаги", "действия"),
    "outputs": ("outputs", "result", "artifacts", "результаты", "выходы", "что получается"),
    "recipients": ("recipients", "receivers", "toWhom", "получатели", "кому передается"),
    "controls": ("controls", "checks", "criteria", "проверки", "контроль"),
    "exceptions": ("exceptions", "escalations", "risks", "исключения", "эскалации"),
}

_PROCESS_FIELD_TO_FUNCTION_FIELD = {
    "workLocation": "tool",
    "objects": "tool",
    "frequency": "periodicity",
    "trigger": "triggerAction",
    "deadlines": "periodicity",
    "steps": "userAction",
}

# Knowledge goals after interview for each process (not a fixed question count).
_PROGRESS_REQUIRED_FACTS = (
    "inputs",
    "outputs",
    "deadlines",
    "workLocation",
    "frequency",
    "steps",
)

_WORK_LOCATION_OBJECT_MARKERS = (
    "реестр",
    "журнал",
    "карточ",
    "документ",
    "форма",
    "раздел",
    "справочник",
    "маршрут",
    "задач",
    "поруч",
    "протокол",
    "повест",
    "материал",
    "календар",
    "таблиц",
    "лист",
    "файл",
    "папк",
    "канал",
    "чат",
    "статус",
)

_GENERIC_WORK_LOCATION_WORDS = {
    "1с",
    "1c",
    "erp",
    "microsoft",
    "ms",
    "office",
    "outlook",
    "excel",
    "word",
    "teams",
    "telegram",
    "почта",
    "система",
    "файл",
    "файлы",
    "реестр",
    "реестры",
    "канал",
    "документы",
}


def new_interview_state() -> dict[str, Any]:
    return {
        "version": 2,
        "position": "",
        "sdk_agent_id": "",
        "attachments": [],
        "turns": [],
        "functions": [],
        "processes": [],
        "askedQuestions": [],
        "currentQuestion": {},
        "answerSufficiency": {},
        "answers": [],
        "selectedProcessIds": [],
    }


def normalize_interview_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return new_interview_state()
    state = deepcopy(raw)
    state["version"] = max(2, int(state.get("version") or 1))
    state.setdefault("position", "")
    state.setdefault("sdk_agent_id", "")
    state.setdefault("attachments", [])
    state.setdefault("turns", [])
    state.setdefault("functions", [])
    state.setdefault("processes", [])
    state.setdefault("askedQuestions", [])
    state.setdefault("currentQuestion", {})
    state.setdefault("answerSufficiency", {})
    state.setdefault("answers", [])
    state.setdefault("selectedProcessIds", [])
    if not isinstance(state["position"], str):
        state["position"] = _clean_str(state.get("position"))
    if not isinstance(state["sdk_agent_id"], str):
        state["sdk_agent_id"] = _clean_str(state.get("sdk_agent_id"))
    if not isinstance(state["attachments"], list):
        state["attachments"] = []
    if not isinstance(state["turns"], list):
        state["turns"] = []
    if not isinstance(state["functions"], list):
        state["functions"] = []
    if not isinstance(state["processes"], list):
        state["processes"] = []
    if not isinstance(state["askedQuestions"], list):
        state["askedQuestions"] = []
    if not isinstance(state["currentQuestion"], dict):
        state["currentQuestion"] = {}
    if not isinstance(state["answerSufficiency"], dict):
        state["answerSufficiency"] = {}
    if not isinstance(state["answers"], list):
        state["answers"] = []
    if not isinstance(state["selectedProcessIds"], list):
        state["selectedProcessIds"] = []
    selected = _clean_process_ids(state.get("selectedProcessIds"))
    if not selected:
        for turn in reversed(state.get("turns") or []):
            if not isinstance(turn, dict):
                continue
            selected = parse_selected_process_ids(str(turn.get("message") or ""))
            if selected:
                break
    state["selectedProcessIds"] = selected
    return state


def set_interview_position(state: Any, position: str) -> dict[str, Any]:
    out = normalize_interview_state(state)
    out["position"] = _clean_str(position)
    return out


def set_sdk_agent_id(state: Any, agent_id: str) -> dict[str, Any]:
    out = normalize_interview_state(state)
    out["sdk_agent_id"] = _clean_str(agent_id)
    return out


def interview_sdk_agent_id(state: Any) -> str:
    return _clean_str(normalize_interview_state(state).get("sdk_agent_id"))


def interview_write_document(state: Any, *, force_create: bool = False) -> bool:
    if force_create:
        return True
    raw = state if isinstance(state, dict) else {}
    return bool(raw.get("document_write_required"))


def interview_has_attachment_text(state: Any) -> bool:
    interview = normalize_interview_state(state)
    for item in interview.get("attachments") or []:
        if isinstance(item, dict) and _clean_str(item.get("text")):
            return True
    return False


def interview_has_processes(state: Any) -> bool:
    interview = normalize_interview_state(state)
    for item in interview.get("processes") or []:
        if isinstance(item, dict) and _clean_str(item.get("id") or item.get("title")):
            return True
    return False


def interview_use_tools(
    state: Any,
    *,
    force_create: bool = False,
    new_attachments: bool = False,
) -> bool:
    if interview_write_document(state, force_create=force_create):
        return True
    if new_attachments:
        return True
    return interview_has_attachment_text(state) and not interview_has_processes(state)


def leading_question_text(raw: Any) -> str:
    text = _clean_str(raw)
    if not text or text.startswith("{") or text.startswith("["):
        return ""
    parts = re.split(r"\n\s*```(?:json)?\s*\n\s*\{", text, maxsplit=1)
    if len(parts) > 1:
        return _clean_str(parts[0])
    parts = re.split(r"\n\s*\{", text, maxsplit=1)
    return _clean_str(parts[0]) if parts else ""


def interview_snapshot(state: Any) -> dict[str, Any]:
    return _prompt_state(normalize_interview_state(state))


def is_replacement_garbage(value: Any) -> bool:
    """True when Cyrillic was lost to ASCII '?' replacement."""
    text = str(value or "").strip()
    if len(text) < 8:
        return False
    qmarks = text.count("?")
    if qmarks < 8:
        return False
    if re.search(r"[А-Яа-яЁё]", text):
        return False
    return qmarks >= max(8, len(text) // 3)


def normalize_process_id(value: Any) -> str:
    text = _clean_str(value)
    if not text:
        return ""
    folded = text.replace("_", "-")
    match = re.fullmatch(r"(?i)b-(p\d+)", folded)
    if match:
        return match.group(1).lower()
    match = re.fullmatch(r"(?i)p\d+", folded)
    if match:
        return folded.lower()
    return text


def _is_internal_process_label(value: Any) -> bool:
    text = _clean_str(value)
    if not text:
        return True
    return bool(re.fullmatch(r"(?i)[pf]\d+", text.replace("_", "-")))


def _process_display_title(process: dict[str, Any], *, index: int = 0) -> str:
    title = _clean_str(process.get("title") or process.get("name") or process.get("description"))
    process_id = normalize_process_id(process.get("id") or process.get("processId"))
    if title and not _is_internal_process_label(title):
        return title
    facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
    for key in ("steps", "outputs", "inputs"):
        raw = facts.get(key)
        if isinstance(raw, list):
            for item in raw:
                text = _clean_str(item)
                if text and not _is_internal_process_label(text):
                    return text[:80]
        else:
            text = _clean_str(raw)
            if text and not _is_internal_process_label(text):
                return text[:80]
    if index > 0:
        return f"Процесс {index}"
    if process_id and not _is_internal_process_label(process_id):
        return process_id
    return "выбранный процесс"


def _clean_process_ids(value: Any) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        process_id = normalize_process_id(item)
        if not process_id or process_id in seen:
            continue
        seen.add(process_id)
        out.append(process_id)
    return out


def parse_selected_process_ids(message: str) -> list[str]:
    text = _clean_str(message)
    if not text:
        return []
    match = re.search(r"(?im)^\s*выбраны процессы\s*:\s*(.+)$", text)
    if not match:
        return []
    first_line = match.group(1).splitlines()[0]
    found = re.findall(r"(?i)\bb-p\d+\b|\bp\d+\b", first_line)
    extra = re.findall(r"(?im)^\s*-\s*(b-p\d+|p\d+)\b", text)
    ids = _clean_process_ids([*found, *extra])
    if ids:
        return ids
    tokens = []
    for part in re.split(r"[,;]", first_line):
        token = (part.strip().split() or [""])[0].strip(".:;")
        if token:
            tokens.append(token)
    return _clean_process_ids(tokens)


def is_process_select_message(value: Any) -> bool:
    text = _fold(str(value or ""))
    return any(
        marker in text
        for marker in (
            "отметьте нужн",
            "отметьте процесс",
            "выберите процесс",
            "извлечены процессы",
        )
    )


def selected_process_ids(state: Any) -> list[str]:
    return _clean_process_ids(normalize_interview_state(state).get("selectedProcessIds"))


def interview_progress(state: Any) -> dict[str, Any]:
    """Progress for the regulation interview UI: answered / remaining by process gaps."""
    interview = normalize_interview_state(state)
    selected = selected_process_ids(interview)
    empty = {
        "answered": 0,
        "remaining": 0,
        "total": 0,
        "currentProcessId": "",
        "currentProcessTitle": "",
        "currentProcessIndex": 0,
        "processCount": 0,
        "visible": False,
    }
    if not selected:
        return empty
    by_id = _selected_processes_in_order(interview, selected)
    if not by_id:
        return {**empty, "processCount": len(selected), "visible": True}
    answered = 0
    remaining = 0
    current_id = ""
    current_title = ""
    current_index = 0
    position = _clean_str(interview.get("position"))
    for index, process in enumerate(by_id, start=1):
        process_id = normalize_process_id(process.get("id") or process.get("processId"))
        open_fields = _process_open_fields(process, interview, position=position)
        closed = _process_closed_count(process, open_fields)
        answered += closed
        remaining += len(open_fields)
        if not current_id and open_fields and _role_status(process) != ROLE_FOREIGN:
            current_id = process_id
            current_title = _process_display_title(process, index=index)
            current_index = index
    if not current_id and by_id:
        last = by_id[-1]
        current_id = normalize_process_id(last.get("id") or last.get("processId"))
        current_title = _process_display_title(last, index=len(by_id))
        current_index = len(by_id)
    total = answered + remaining
    return {
        "answered": answered,
        "remaining": remaining,
        "total": total,
        "currentProcessId": current_id,
        "currentProcessTitle": current_title,
        "currentProcessIndex": current_index,
        "processCount": len(by_id),
        "visible": True,
    }


def current_interview_process_id(state: Any) -> str:
    progress = interview_progress(state)
    return _clean_str(progress.get("currentProcessId"))


def question_for_selected_processes(state: Any) -> ReadyBlocker | None:
    interview = normalize_interview_state(state)
    selected = selected_process_ids(interview)
    processes = _selected_processes_in_order(interview, selected) if selected else [
        item for item in interview.get("processes") or [] if isinstance(item, dict)
    ]
    current_id = current_interview_process_id(interview)
    if current_id:
        processes = [
            item
            for item in processes
            if normalize_process_id(item.get("id") or item.get("processId")) == current_id
        ] or processes
    position = _clean_str(interview.get("position"))
    for index, process in enumerate(processes, start=1):
        if _role_status(process) == ROLE_FOREIGN:
            continue
        title = _process_display_title(process, index=index)
        process_id = normalize_process_id(process.get("id") or process.get("processId"))
        open_fields = _process_open_fields(process, interview, position=position)
        if "roleStatus" in open_fields:
            return ReadyBlocker(
                message=(
                    f"Процесс «{title}» в документе выглядит неоднозначно. "
                    "Он относится к вашей должности?"
                ),
                quick_answers=["Да, это моя обязанность", "Нет, другая роль", "Частично, уточню"],
                function_id=process_id,
                field="roleStatus",
            )
        for unknown in _normalize_unknowns(process.get("unknowns")):
            field = _progress_field_key(unknown.get("field"))
            if field not in open_fields:
                continue
            hint = _clean_str(unknown.get("question") or unknown.get("reason"))
            return ReadyBlocker(
                message=_question_message_for_process_gap(title=title, field=field, hint=hint),
                quick_answers=[],
                function_id=process_id,
                field=field,
            )
        for key in _PROGRESS_REQUIRED_FACTS:
            if key not in open_fields:
                continue
            return ReadyBlocker(
                message=_question_message_for_process_gap(title=title, field=key),
                quick_answers=[],
                function_id=process_id,
                field=key,
            )
    return None


def _process_gap_label(field: str) -> str:
    return {
        "inputs": "что поступает на вход",
        "outputs": "какой результат получается",
        "deadlines": "какие сроки выполнения",
        "workLocation": "где читаются и записываются данные",
        "frequency": "как часто нужно выполнять действие",
        "steps": "какая последовательность действий",
        "roleStatus": "относится ли процесс к вашей должности",
    }.get(field, "как это устроено")


def _question_message_for_process_gap(*, title: str, field: str, hint: str = "") -> str:
    label = _process_gap_label(field)
    text = _clean_str(hint)
    if text and ("?" in text or "？" in text):
        if text.lower().startswith("по процессу") or text.lower().startswith("процесс"):
            return text
        return f"По процессу «{title}»: {text}"
    if text:
        cleaned = text.rstrip(" .;")
        return (
            f"По процессу «{title}» не хватает ясности: {cleaned}. "
            f"Уточните, пожалуйста, {label}?"
        )
    return f"По процессу «{title}» не видно, {label}. Как это устроено у вас?"


def _selected_processes_in_order(interview: dict[str, Any], selected: list[str]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in interview.get("processes") or []:
        if not isinstance(item, dict):
            continue
        process_id = normalize_process_id(item.get("id") or item.get("processId"))
        if process_id:
            by_id[process_id] = item
    for item in interview.get("functions") or []:
        if not isinstance(item, dict):
            continue
        process_id = normalize_process_id(item.get("id") or item.get("processId"))
        if process_id and process_id not in by_id:
            by_id[process_id] = {
                "id": process_id,
                "title": _clean_str(item.get("title")),
                "roleStatus": item.get("roleStatus"),
                "knownFacts": {
                    "workLocation": _clean_str(item.get("tool")),
                    "frequency": _clean_str(item.get("periodicity")),
                    "trigger": _clean_str(item.get("triggerAction")),
                    "steps": [_clean_str(item.get("userAction"))] if _clean_str(item.get("userAction")) else [],
                },
                "unknowns": [
                    {"field": gap, "critical": True, "reason": gap}
                    for gap in (item.get("openGaps") or _open_gaps(item, position=_clean_str(interview.get("position"))))
                ],
            }
    out: list[dict[str, Any]] = []
    for process_id in selected:
        process = by_id.get(process_id)
        if process is not None:
            out.append(process)
    return out


def _process_open_fields(
    process: dict[str, Any],
    interview: dict[str, Any],
    *,
    position: str = "",
) -> set[str]:
    if _role_status(process) == ROLE_FOREIGN:
        return set()
    open_fields: set[str] = set()
    if position and _role_status(process) != ROLE_BELONGS:
        open_fields.add("roleStatus")
    facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
    for key in _PROGRESS_REQUIRED_FACTS:
        value = facts.get(key)
        empty = value in (None, "", []) or (
            isinstance(value, list) and not any(str(item).strip() for item in value)
        )
        if empty:
            open_fields.add(key)
            continue
        text = value if isinstance(value, str) else " ".join(
            str(item) for item in value if str(item).strip()
        )
        if key == "workLocation" and _is_vague_work_location(text):
            open_fields.add(key)
        elif key == "steps" and _is_vague_user_action(text):
            open_fields.add(key)
    for unknown in _normalize_unknowns(process.get("unknowns")):
        if not bool(unknown.get("critical")):
            continue
        field = _progress_field_key(unknown.get("field"))
        if field in _PROGRESS_REQUIRED_FACTS or field == "roleStatus":
            # Only keep as open if the required fact is still empty/vague.
            if field == "roleStatus" or field in open_fields or _fact_missing(facts.get(field)):
                open_fields.add(field if field else "unknown")
    process_id = normalize_process_id(process.get("id") or process.get("processId"))
    for func in interview.get("functions") or []:
        if not isinstance(func, dict):
            continue
        if normalize_process_id(func.get("id") or func.get("processId")) != process_id:
            continue
        mapped = {
            "tool": "workLocation",
            "periodicity": "frequency",
            "userAction": "steps",
        }
        for gap in _open_gaps(func, position=position):
            key = mapped.get(gap) or _progress_field_key(gap)
            if key in _PROGRESS_REQUIRED_FACTS and _fact_missing(facts.get(key)):
                open_fields.add(key)
    return open_fields


def _fact_missing(value: Any) -> bool:
    if value in (None, "", []):
        return True
    if isinstance(value, list):
        return not any(str(item).strip() for item in value)
    return not str(value).strip()


def _process_closed_count(process: dict[str, Any], open_fields: set[str]) -> int:
    if _role_status(process) == ROLE_FOREIGN:
        return len(_PROGRESS_REQUIRED_FACTS)
    closed = 0
    for key in _PROGRESS_REQUIRED_FACTS:
        if key not in open_fields:
            closed += 1
    return closed


def _progress_field_key(value: Any) -> str:
    canonical = _canonical_gap(value)
    if not canonical:
        return ""
    if canonical == "deadlines":
        return "deadlines"
    if canonical == "inputs":
        return "inputs"
    if canonical == "outputs":
        return "outputs"
    for process_key, function_key in _PROCESS_FIELD_TO_FUNCTION_FIELD.items():
        if canonical == function_key or canonical == process_key:
            return process_key
    if canonical in _PROGRESS_REQUIRED_FACTS or canonical == "roleStatus":
        return canonical
    return canonical


def _selected_ids_from_payload(payload: dict[str, Any]) -> list[str]:
    pipeline = payload.get("pipeline") if isinstance(payload.get("pipeline"), dict) else {}
    interview = payload.get("interview") if isinstance(payload.get("interview"), dict) else {}
    return _clean_process_ids(
        pipeline.get("selectedProcessIds")
        or interview.get("selectedProcessIds")
        or payload.get("selectedProcessIds")
    )


def owned_functions(state: Any) -> list[dict[str, Any]]:
    interview = normalize_interview_state(state)
    out: list[dict[str, Any]] = []
    for func in interview.get("functions") or []:
        if not isinstance(func, dict):
            continue
        if _role_status(func) == ROLE_FOREIGN:
            continue
        out.append(func)
    return out


def append_user_turn(state: Any, message: str, attachments: list[dict]) -> dict[str, Any]:
    out = normalize_interview_state(state)
    out.pop("document_write_required", None)
    attachment_refs: list[str] = []
    for item in attachments:
        name = str(item.get("name") or "file")
        text = str(item.get("text") or "")
        existing = _find_attachment(out, name=name, text=text)
        if existing is None:
            existing = {
                "id": f"file{len(out['attachments']) + 1}",
                "name": Path(name).name,
                "kind": str(item.get("kind") or "text"),
                "text": text,
            }
            out["attachments"].append(existing)
        attachment_refs.append(str(existing.get("id") or existing.get("name") or name))
    out["turns"].append(
        {
            "role": "user",
            "message": message.strip(),
            "attachments": attachment_refs,
        }
    )
    out["turns"] = out["turns"][-40:]
    selected = parse_selected_process_ids(message)
    if selected:
        out["selectedProcessIds"] = selected
    _attach_answer_to_current_question(out, message)
    _apply_role_answer(out, message)
    return out


def merge_agent_payload(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    out = normalize_interview_state(state)
    answer_sufficiency = _extract_answer_sufficiency(payload)
    next_question = payload.get("nextQuestion") if isinstance(payload.get("nextQuestion"), dict) else {}
    _apply_progress_from_user_answer(
        out,
        answer_sufficiency=answer_sufficiency,
        next_question=next_question,
    )
    if answer_sufficiency:
        _record_answer_sufficiency(out, answer_sufficiency)
    incoming = _extract_functions(payload)
    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        incoming_item = _normalize_function(raw, fallback_index=len(out["functions"]) + 1)
        if not incoming_item:
            continue
        existing = _find_function(out["functions"], incoming_item)
        if existing is None:
            out["functions"].append(incoming_item)
        else:
            _merge_function(existing, incoming_item)
    position = _clean_str(out.get("position"))
    for func in out["functions"]:
        func["roleStatus"] = _resolve_role_status(func, position)
        func["openGaps"] = _open_gaps(func, position=position)
        func["sourceRefs"] = _clean_source_refs(func.get("sourceRefs"))
        _merge_process(out, _process_from_function(func, fallback_index=len(out["processes"]) + 1))
    for raw in _extract_processes(payload):
        if not isinstance(raw, dict):
            continue
        process = _normalize_process(raw, fallback_index=len(out["processes"]) + 1)
        if process:
            _merge_process(out, process)
    for process in out["processes"]:
        if not isinstance(process, dict):
            continue
        process["roleStatus"] = _resolve_role_status(process, position)
        process["sourceRefs"] = _clean_source_refs(process.get("sourceRefs"))
        process["unknowns"] = _prune_filled_unknowns(process)
    incoming_selected = _selected_ids_from_payload(payload)
    if incoming_selected:
        out["selectedProcessIds"] = incoming_selected
    elif out.get("selectedProcessIds"):
        out["selectedProcessIds"] = _clean_process_ids(out.get("selectedProcessIds"))
    return out


def creation_interviewer_rules() -> str:
    return (
        "Ты в режиме agent: отвечай только текстом, без инструментов. "
        "Не пиши Cursor-план и не меняй файлы. Вместо плана потом будет регламент.\n"
        "Не вызывай Read, Grep, Glob, ls и любые другие tools. Не читай файлы с диска.\n"
        "Все нужные факты уже есть в сообщении: карта интервью и тексты вложений.\n"
        "Работай только по этим текстам и ответам пользователя. Не используй шаблоны, "
        "эталоны и типовые догадки как содержание регламента.\n"
        "Один ход = один вопрос пользователю. Не констатируй пробел ('не указано', 'не раскрыто', "
        "'упомянуто, но...') без вопроса: сразу спроси недостающий факт простым языком.\n"
        "После вопроса с новой строки верни компактный JSON без markdown: status, message "
        "(тот же вопрос), quickAnswers, nextQuestion и только изменённый процесс в "
        "interview.processes. document оставляй пустым, пока status не ready.\n"
        "Если selectedProcessIds уже есть, не проси отметить процессы снова.\n"
        "Спрашивай строго по одному текущему процессу: сначала закрой его пробелы, "
        "потом переходи к следующему id из selectedProcessIds. Не прыгай между процессами.\n"
        "По процессу к концу опроса должны быть ясны (это цели знания, не лимит вопросов): "
        "входы, результат, сроки выполнения, источники чтения и записи данных, частота, "
        "последовательность действий. Число вопросов не фиксировано: задавай столько уточнений, "
        "сколько нужно, чтобы закрыть пробел, но не спрашивай то, что уже есть в тексте или knownFacts. "
        "Не добавляй лишние обязательные темы вроде получателей или триггера, если без них уже можно "
        "закрыть цели выше. Один ход = один вопрос.\n"
        "Не повторяй askedQuestions.\n"
    )


def process_extraction_model_rules(*, position: str = "") -> str:
    """Granularity used when processes are extracted from uploaded documents."""
    who = f"«{position}»" if str(position or "").strip() else "пользователя"
    return (
        "Один process — это контур ответственности должности, а не отдельный глагол и не шаг.\n"
        f"Выделяй processes только для должности {who} и её явных алиасов.\n"
        "Шаги, проверки, правки, пересчёт, уведомления и смена данных внутри одного контура "
        "пиши в knownFacts.steps. Не делай из них отдельные processes.\n"
        "Пример: «Контроль календаря ПСД» включает проверку календаря и внесение изменений — "
        "это один process. Не выделяй «Изменение календаря» отдельно.\n"
        "Не дроби один контур по системам (Outlook и Excel), по частоте или по получателям.\n"
        "Отдельный process только если другой объект, другой цикл или другой бизнес-результат "
        "(командировки, календарь ПСД, документооборот инициатив).\n"
        "К каждому process сразу заполняй knownFacts: inputs, outputs, deadlines, "
        "workLocation, frequency, steps.\n"
    )


def creation_system_rules(*, force_create: bool = False) -> str:
    force = (
        "Пользователь запросил принудительное создание. Можно вернуть status='ready' по текущим "
        "проверенным данным, но нельзя выдавать предположения как факты."
        if force_create
        else (
            "Не возвращай status='ready', пока по каждому выбранному процессу должности не ясны "
            "входы, результат, сроки, источники чтения/записи данных, частота и последовательность "
            "действий (или явно подтверждено, что факта нет)."
        )
    )
    return (
        "Ты помогаешь создать точный регламент действий пользователя. "
        "Пока опрос не закрыт, работай в режиме agent: читай материалы только когда есть "
        "новые файлы, задавай вопросы текстом, не пиши Cursor-план и не меняй файлы. "
        "Регламент пишется только после закрытия опроса.\n"
        "Работай только по текстам приложенных файлов и ответам пользователя. Не используй шаблоны, "
        "эталоны и типовые догадки как содержание регламента.\n"
        "Если приложено несколько файлов, анализируй их вместе и не теряй ранее приложенные файлы.\n"
        "Конвейер строго такой: прочитать файлы, извлечь процессы, дать выбор, сохранить "
        "interview.selectedProcessIds, затем спрашивать только по выбранным процессам, затем "
        "собрать регламент. Если selectedProcessIds уже есть, этап выбора закрыт: не проси "
        "отметить процессы снова, не повторяй список и не возвращай pipeline.stage='select'. "
        "По выбранным процессам иди строго по порядку selectedProcessIds: полностью закрой "
        "пробелы текущего процесса, затем переходи к следующему. Не задавай вопрос по другому "
        "процессу, пока текущий не закрыт.\n"
        "Сначала извлеки функциональные блоки из документов. Для каждого блока определи roleStatus: "
        "belongs (это обязанность указанной должности), foreign (другая роль) или unclear (сомнение).\n"
        "Если исполнитель в тексте не указан, указан общо или не совпадает с должностью пользователя, "
        "roleStatus=unclear и сначала спроси принадлежность. Чужие роли (foreign) не включай в регламент.\n"
        "Главная рабочая модель - interview.processes.knownFacts. К концу опроса по каждому "
        "belongs-процессу должны быть ясны эти цели знания (это не лимит в N вопросов):\n"
        "- inputs: что поступает на вход;\n"
        "- outputs: какой результат получается;\n"
        "- deadlines: сроки выполнения;\n"
        "- workLocation: источники чтения и записи данных (система, файл, раздел, реестр);\n"
        "- frequency: как часто нужно выполнять действие;\n"
        "- steps: последовательность действий пользователя.\n"
        "Число вопросов не фиксировано: задавай столько уточнений, сколько нужно, чтобы закрыть "
        "пробел. Не злоупотребляй: если факт уже в документе или knownFacts - не спрашивай снова, "
        "запиши его и иди дальше. Не делай обязательными темы вроде получателей или триггера "
        "только ради анкеты, если цели выше уже закрыты.\n"
        "interview.functions - только совместимый краткий срез (tool/periodicity/triggerAction/userAction), "
        "не веди опрос по четырём полям функции отдельно от knownFacts.\n"
        "Каждый последний ответ оцени в answerSufficiency: closed, partial или not_answered. "
        "В nextQuestion укажи targetFact из inputs|outputs|deadlines|workLocation|frequency|steps, "
        "alreadyKnown, missingFact и whyThisQuestion. В message - только текст вопроса простым языком.\n"
        "Не повторяй askedQuestions. Один ход = один вопрос по текущему процессу.\n"
        "Не предлагай пользователю подтвердить выдуманный ответ. quickAnswers — только если есть "
        "2-6 вариантов из текста вложения или уже данных ответов; без Outlook/Excel/1C и других "
        "систем наугад. Если вариантов нет, верни пустой quickAnswers. "
        "В message всегда один реальный вопрос к пользователю. Запрещено вместо вопроса писать "
        "констатацию пробела вроде 'срок не раскрыт', 'в тексте не указано', 'пробелов нет'. "
        "Если факта нет - спроси его.\n"
        "Пока status='need_more', не пиши полный document и не повторяй весь список функций. "
        "В interview.processes верни только новый или изменённый процесс. "
        "Сначала напиши пользователю только текст одного вопроса простым языком, "
        "без JSON и без markdown. Не начинай ответ с фигурной скобки.\n"
        "Когда все обязательные цели знания закрыты и можно вернуть status='ready', document обязателен. "
        "Его должен написать Cursor SDK как самостоятельный регламент процесса: связный документ, "
        "понятный без истории чата. Вынеси в него подтверждённые входы, результаты, сроки, "
        "источники данных, частоту, последовательность действий и релевантное содержание "
        "materials/*, не выдумывая фактов.\n"
        "Структуру разделов выбирай по фактическому процессу. Не используй фиксированный шаблон глав "
        "и не копируй лейблы полей interview как тело документа.\n"
        f"{force}\n"
        "После вопроса с новой строки верни компактный JSON без markdown. Контракт:\n"
        "{\n"
        '  "status": "need_more|ready",\n'
        '  "message": "один вопрос или сообщение о готовности",\n'
        '  "positions": ["..."],\n'
        '  "quickAnswers": ["вариант 1", "вариант 2"],\n'
        '  "answerSufficiency": {\n'
        '    "status": "closed|partial|not_answered",\n'
        '    "processId": "f1",\n'
        '    "field": "inputs|outputs|deadlines|workLocation|frequency|steps|roleStatus",\n'
        '    "answerSummary": "что именно стало известно",\n'
        '    "missingFacts": ["чего не хватает"],\n'
        '    "reason": "почему ответ достаточен или недостаточен"\n'
        "  },\n"
        '  "nextQuestion": {\n'
        '    "processId": "f1",\n'
        '    "targetFact": "inputs|outputs|deadlines|workLocation|frequency|steps",\n'
        '    "alreadyKnown": ["что уже известно и не надо спрашивать снова"],\n'
        '    "missingFact": "какой факт нужен сейчас",\n'
        '    "whyThisQuestion": "почему без этого нельзя закрыть процесс",\n'
        '    "text": "вопрос пользователю простым языком"\n'
        "  },\n"
        '  "interview": {\n'
        '    "processes": [\n'
        "      {\n"
        '        "id": "f1",\n'
        '        "title": "короткое название процесса",\n'
        '        "actor": "должность из документа",\n'
        '        "roleStatus": "belongs|foreign|unclear",\n'
        '        "sourceRefs": [{"file": "имя файла", "quote": "цитата"}],\n'
        '        "knownFacts": {\n'
        '          "inputs": ["входные документы или события"],\n'
        '          "outputs": ["результат"],\n'
        '          "deadlines": "сроки выполнения",\n'
        '          "workLocation": "где читают и пишут данные",\n'
        '          "frequency": "как часто",\n'
        '          "steps": ["последовательность действий"]\n'
        "        },\n"
        '        "unknowns": [{"field": "inputs", "reason": "чего нет в тексте", "critical": true}],\n'
        '        "askedQuestions": [{"message": "что спрашивали", "answer": "ответ", "sufficiency": "partial"}]\n'
        "      }\n"
        "    ],\n"
        '    "functions": []\n'
        "  },\n"
        '  "document": {"title": "", "sections": [{"number": "1", "title": "", "paragraphs": [], "items": []}]}\n'
        "}"
    )


def build_creation_prompt(
    *,
    state: Any,
    message: str,
    initial: bool,
    force_create: bool,
    include_attachment_bodies: bool = True,
) -> str:
    interview = normalize_interview_state(state)
    inventory = _prompt_state(interview)
    if not include_attachment_bodies:
        inventory["attachments"] = _prompt_attachment_refs(inventory.get("attachments") or [])
    action = "Начни" if initial else "Продолжай"
    files_hint = (
        "Тексты приложенных файлов уже лежат в рабочей папке: interview.json и materials/*.txt. "
        "Прочитай их оттуда. Не выдумывай содержание документов.\n"
        if not include_attachment_bodies
        else (
            "Отвечай только текстом, без инструментов. Не читай файлы с диска: "
            "тексты вложений уже в этом сообщении.\n"
        )
    )
    focus = _current_process_prompt_hint(interview)
    return (
        f"{action} интервью.\n"
        f"{creation_system_rules(force_create=force_create)}\n"
        f"{files_hint}"
        f"{focus}"
        "Текущее постоянное состояние интервью:\n"
        f"{json.dumps(inventory, ensure_ascii=False, indent=2)}\n"
        f"Последний ответ пользователя: {message.strip()}"
    )


def build_followup_creation_prompt(
    *,
    message: str,
    force_create: bool,
    state: Any = None,
    write_document: bool = False,
) -> str:
    force = (
        "Пользователь запросил принудительное создание. Можно вернуть status='ready' по текущим данным."
        if force_create
        else (
            "Не возвращай status='ready', пока есть unclear roleStatus, открытые gaps или "
            "критичные unknowns по процессам должности."
        )
    )
    snapshot = ""
    focus = ""
    if state is not None:
        interview = normalize_interview_state(state)
        inventory = _prompt_state(interview)
        inventory["attachments"] = _prompt_attachment_refs(inventory.get("attachments") or [])
        focus = _current_process_prompt_hint(interview)
        snapshot = (
            "Текущая карта интервью. Не читай файлы и не вызывай инструменты, "
            "используй только это сообщение и историю диалога:\n"
            f"{json.dumps(inventory, ensure_ascii=False, indent=2)}\n"
        )
    if write_document or force_create:
        return (
            "Продолжи то же интервью. История диалога уже у тебя. "
            "Прочитай обновлённый interview.json и materials/* в рабочей папке.\n"
            "Если interview.selectedProcessIds не пустой, этап выбора закрыт: не проси отметить "
            "процессы снова и не возвращай pipeline.stage='select'.\n"
            f"{force}\n"
            f"Последний ответ пользователя: {message.strip()}\n"
            "Не задавай новый вопрос: верни status='ready' и полный document как самостоятельный "
            "связный регламент процесса. Вынеси в него релевантное содержание материалов "
            "пользователя, подтверждённое файлами или ответами. "
            "Не используй interview.functions как оглавление и не пиши одинаковые карточки функций "
            "с повтором 'Основание' и 'Предположение' в каждом блоке."
        )
    return (
        "Продолжи то же интервью текстом, без инструментов. История диалога уже у тебя. "
        "Не читай interview.json и materials/* с диска. Не пиши Cursor-план и не меняй файлы.\n"
        f"{focus}"
        f"{snapshot}"
        "Если interview.selectedProcessIds не пустой, этап выбора закрыт: не проси отметить "
        "процессы снова и не возвращай pipeline.stage='select'. Задавай вопросы только по "
        "текущему незакрытому процессу, по одному за ход; к следующему processId переходи "
        "только после закрытия текущего.\n"
        f"{force}\n"
        f"Последний ответ пользователя: {message.strip()}\n"
        "Сначала оцени последний ответ в answerSufficiency. Цели знания по процессу: "
        "inputs, outputs, deadlines, workLocation (чтение/запись данных), frequency, steps "
        "(последовательность действий). Число вопросов не фиксировано. "
        "Если факт уже есть в knownFacts или в тексте вложения - не спрашивай повторно.\n"
        "Веди interview.processes как карту процесса: knownFacts, unknowns, askedQuestions, "
        "currentQuestion. interview.functions оставляй только как краткий совместимый срез.\n"
        "Перед новым вопросом проверь askedQuestions: не повторяй то же самое. "
        "Сначала напиши только текст следующего вопроса простым языком. Не начинай ответ "
        "с фигурной скобки. Затем с новой строки верни компактный JSON: status, message, "
        "quickAnswers, nextQuestion и только изменённый процесс.\n"
        "Если в interview.json есть document_write_required=true, не задавай новый вопрос: "
        "верни status='ready' и полный document как самостоятельный связный регламент процесса. "
        "document оставляй пустым, пока status не ready. При status='ready' document обязателен: "
        "это должен быть полный деловой текст, а не список полей interview. Вынеси в него "
        "релевантное содержание материалов пользователя, подтверждённое файлами или ответами. "
        "Не используй interview.functions как оглавление и не пиши одинаковые карточки функций "
        "с повтором 'Основание' и 'Предположение' в каждом блоке."
    )


def _current_process_prompt_hint(state: Any) -> str:
    progress = interview_progress(state)
    process_id = _clean_str(progress.get("currentProcessId"))
    if not process_id:
        return ""
    index = int(progress.get("currentProcessIndex") or 0)
    count = int(progress.get("processCount") or 0)
    title = _clean_str(progress.get("currentProcessTitle")) or _process_display_title(
        {"id": process_id, "title": ""},
        index=index,
    )
    return (
        f"Сейчас опрашивай только процесс {index} из {count}: id={process_id}, "
        f"«{title}». nextQuestion.processId должен быть {process_id}. "
        "Цели знания: inputs, outputs, deadlines, workLocation, frequency, steps. "
        "Вопросов может быть больше одного на цель, если нужно уточнение.\n"
    )


def remember_assistant_question(
    state: Any,
    *,
    message: str,
    quick_answers: list[str] | None = None,
    function_id: str = "",
    field: str = "",
    process_id: str = "",
    intent: str = "",
    already_known: list[str] | None = None,
    missing_fact: str = "",
    why_this_question: str = "",
) -> tuple[dict[str, Any], str]:
    out = normalize_interview_state(state)
    text = _clean_str(message)
    question_id = f"q{len(out['askedQuestions']) + 1}"
    canonical_field = _canonical_gap(field)
    duplicate = _question_was_asked(out, message=text, function_id=function_id, field=canonical_field)
    question = {
        "id": question_id,
        "message": text,
        "quickAnswers": list(quick_answers or []),
        "functionId": _clean_str(function_id),
        "processId": _clean_str(process_id or function_id),
        "field": canonical_field,
        "intent": _clean_str(intent) or canonical_field,
        "alreadyKnown": _clean_list(already_known or []),
        "missingFact": _clean_str(missing_fact),
        "whyThisQuestion": _clean_str(why_this_question),
        "answer": "",
        "sufficiency": "pending",
        "missingFacts": [],
        "duplicate": duplicate,
    }
    out["currentQuestion"] = dict(question)
    out["askedQuestions"].append(dict(question))
    out["askedQuestions"] = out["askedQuestions"][-40:]
    return out, text


def followup_blocker(payload: dict[str, Any], state: Any) -> ReadyBlocker | None:
    insufficiency = _answer_sufficiency_blocker(payload, state)
    if insufficiency is not None:
        return insufficiency
    return _current_question_blocker(state)


def ready_blocker(payload: dict[str, Any], state: Any) -> ReadyBlocker | None:
    if payload.get("status") != "ready":
        return None
    interview = merge_agent_payload(state, payload)
    selected = selected_process_ids(interview)
    if selected:
        gap = question_for_selected_processes(interview)
        if gap is not None:
            return gap
        progress = interview_progress(interview)
        if int(progress.get("remaining") or 0) > 0:
            return ReadyBlocker(
                message=(
                    "По выбранным процессам ещё не ясны входы, результат, сроки, "
                    "источники данных, частота или последовательность действий. "
                    "Уточните недостающий факт."
                ),
                quick_answers=[],
                function_id=_clean_str(progress.get("currentProcessId")),
                field="",
            )
        return None
    functions = [item for item in interview.get("functions") or [] if isinstance(item, dict)]
    position = _clean_str(interview.get("position"))
    owned = [item for item in functions if _role_status(item) != ROLE_FOREIGN]
    if not owned:
        return ReadyBlocker(
            message=(
                "Я пока не вижу полного списка функций пользователя. Приложите файл с обязанностями "
                "или опишите первую функцию, которую нужно включить в регламент."
            ),
            quick_answers=[
                "Приложу файл с обязанностями",
                "Опишу функции сообщением",
                "Начать с функций из моей должности",
            ],
            field="functions",
        )
    for func in owned:
        gaps = _open_gaps(func, position=position)
        if gaps:
            field = gaps[0]
            return _question_for_gap(func, field, position=position)
    process_blocker = _process_unknown_blocker(interview)
    if process_blocker is not None:
        return process_blocker
    return None


def _find_attachment(state: dict[str, Any], *, name: str, text: str) -> dict[str, Any] | None:
    for item in state.get("attachments") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "") == Path(name).name and str(item.get("text") or "") == text:
            return item
    return None


def _extract_functions(payload: dict[str, Any]) -> list[Any]:
    interview = payload.get("interview") if isinstance(payload.get("interview"), dict) else {}
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
    for source in (interview, inventory, payload):
        items = source.get("functions") if isinstance(source, dict) else None
        if isinstance(items, list):
            return items
    return []


def _extract_processes(payload: dict[str, Any]) -> list[Any]:
    interview = payload.get("interview") if isinstance(payload.get("interview"), dict) else {}
    inventory = payload.get("inventory") if isinstance(payload.get("inventory"), dict) else {}
    for source in (interview, inventory, payload):
        items = source.get("processes") if isinstance(source, dict) else None
        if isinstance(items, list):
            return items
    return []


def _extract_answer_sufficiency(payload: dict[str, Any]) -> dict[str, Any]:
    interview = payload.get("interview") if isinstance(payload.get("interview"), dict) else {}
    for source in (payload, interview):
        raw = source.get("answerSufficiency") if isinstance(source, dict) else None
        if isinstance(raw, dict):
            return _normalize_answer_sufficiency(raw)
    return {}


def _normalize_function(raw: dict[str, Any], *, fallback_index: int) -> dict[str, Any]:
    title = _clean_str(raw.get("title") or raw.get("name") or raw.get("description"))
    func_id = _clean_str(raw.get("id") or raw.get("functionId")) or f"f{fallback_index}"
    if not title and not func_id:
        return {}
    item = {
        "id": func_id,
        "title": title or func_id,
        "actor": _clean_str(raw.get("actor") or raw.get("position")),
        "sourceRefs": _clean_source_refs(raw.get("sourceRefs")),
        "tool": _field_value(raw, "tool"),
        "periodicity": _field_value(raw, "periodicity"),
        "triggerAction": _field_value(raw, "triggerAction"),
        "userAction": _field_value(raw, "userAction"),
        "roleStatus": _normalize_role_status(raw.get("roleStatus")),
    }
    open_gaps = raw.get("openGaps")
    item["openGaps"] = [str(gap) for gap in open_gaps] if isinstance(open_gaps, list) else []
    return item


def _normalize_process(raw: dict[str, Any], *, fallback_index: int) -> dict[str, Any]:
    title = _clean_str(raw.get("title") or raw.get("name") or raw.get("description"))
    process_id = _clean_str(raw.get("id") or raw.get("processId") or raw.get("functionId")) or f"p{fallback_index}"
    if not title and not process_id:
        return {}
    known_facts = _normalize_known_facts(raw.get("knownFacts") if isinstance(raw.get("knownFacts"), dict) else raw)
    return {
        "id": process_id,
        "title": title,
        "actor": _clean_str(raw.get("actor") or raw.get("position")),
        "roleStatus": _normalize_role_status(raw.get("roleStatus")),
        "sourceRefs": _clean_source_refs(raw.get("sourceRefs")),
        "knownFacts": known_facts,
        "unknowns": _normalize_unknowns(raw.get("unknowns")),
        "askedQuestions": _normalize_questions(raw.get("askedQuestions")),
        "currentQuestion": raw.get("currentQuestion") if isinstance(raw.get("currentQuestion"), dict) else {},
    }


def _normalize_known_facts(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    facts: dict[str, Any] = {}
    for field, aliases in _PROCESS_FACT_ALIASES.items():
        value = _value_by_alias(raw, aliases)
        if field in {"steps", "inputs", "outputs", "recipients", "controls", "exceptions", "objects"}:
            normalized = _clean_list(value)
            if normalized:
                facts[field] = normalized
        else:
            text = _clean_str(value)
            if text:
                facts[field] = text
    return facts


def _value_by_alias(raw: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in raw:
            return raw.get(key)
    return None


def _clean_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in (_clean_str(raw) for raw in value) if item]
    text = _clean_str(value)
    return [text] if text else []


def _normalize_unknowns(raw: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    items = raw if isinstance(raw, list) else []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            fact = _canonical_gap(item.get("field") or item.get("fact") or item.get("missingFact"))
            question = _clean_str(item.get("question") or item.get("message"))
            reason = _clean_str(item.get("reason") or item.get("why"))
            critical = bool(item.get("critical") or item.get("blocking") or item.get("required"))
            source = _clean_str(item.get("source"))
        else:
            fact = _canonical_gap(item)
            question = ""
            reason = _clean_str(item)
            critical = False
            source = ""
        if not fact and not reason and not question:
            continue
        out.append(
            {
                "id": f"u{index}",
                "field": fact,
                "reason": reason,
                "question": question,
                "critical": critical,
                "source": source,
            }
        )
    return out


def _normalize_questions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        message = _clean_str(item.get("message") or item.get("question"))
        if not message:
            continue
        out.append(
            {
                "id": _clean_str(item.get("id")) or f"q{len(out) + 1}",
                "message": message,
                "field": _canonical_gap(item.get("field") or item.get("missingFact")),
                "intent": _clean_str(item.get("intent")),
                "answer": _clean_str(item.get("answer")),
                "sufficiency": _normalize_sufficiency_status(item.get("sufficiency")),
                "missingFacts": _clean_list(item.get("missingFacts")),
            }
        )
    return out


def _normalize_answer_sufficiency(raw: dict[str, Any]) -> dict[str, Any]:
    status = _normalize_sufficiency_status(raw.get("status") or raw.get("result") or raw.get("state"))
    if not status:
        return {}
    return {
        "status": status,
        "processId": _clean_str(raw.get("processId") or raw.get("functionId")),
        "functionId": _clean_str(raw.get("functionId") or raw.get("processId")),
        "field": _canonical_gap(raw.get("field") or raw.get("missingFact") or raw.get("intent")),
        "intent": _clean_str(raw.get("intent")),
        "answerSummary": _clean_str(raw.get("answerSummary") or raw.get("summary")),
        "missingFacts": _clean_list(raw.get("missingFacts") or raw.get("missing")),
        "reason": _clean_str(raw.get("reason") or raw.get("why")),
    }


def _normalize_sufficiency_status(raw: Any) -> str:
    text = _clean_str(raw).lower()
    if text in {"closed", "complete", "ok", "закрыто", "достаточно"}:
        return "closed"
    if text in {"partial", "partially_closed", "частично", "неполно"}:
        return "partial"
    if text in {"not_answered", "unanswered", "no", "нет ответа", "не отвечает"}:
        return "not_answered"
    return text if text in _ANSWER_SUFFICIENCY_STATUSES else ""


def _field_value(raw: dict[str, Any], field: str) -> str:
    for key in _FIELD_ALIASES[field]:
        if key in raw:
            value = raw.get(key)
            if isinstance(value, list):
                return ", ".join(_clean_str(item) for item in value if _clean_str(item))
            return _clean_str(value)
    return ""


def _find_function(functions: list[Any], incoming: dict[str, Any]) -> dict[str, Any] | None:
    incoming_id = _clean_str(incoming.get("id"))
    incoming_title = _clean_str(incoming.get("title")).lower()
    for item in functions:
        if not isinstance(item, dict):
            continue
        if incoming_id and _clean_str(item.get("id")) == incoming_id:
            return item
        if incoming_title and _clean_str(item.get("title")).lower() == incoming_title:
            return item
    return None


def _merge_function(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key in ("title", "actor", "tool", "periodicity", "triggerAction", "userAction"):
        value = _clean_str(incoming.get(key))
        if value:
            existing[key] = value
    incoming_role = _normalize_role_status(incoming.get("roleStatus"))
    _apply_incoming_role_status(existing, incoming_role)
    refs = _clean_source_refs(incoming.get("sourceRefs"))
    if refs:
        current = _clean_source_refs(existing.get("sourceRefs"))
        existing["sourceRefs"] = current + [ref for ref in refs if ref not in current]


def _process_from_function(func: dict[str, Any], *, fallback_index: int) -> dict[str, Any]:
    process_id = _clean_str(func.get("id")) or f"p{fallback_index}"
    known_facts: dict[str, Any] = {}
    tool = _clean_str(func.get("tool"))
    periodicity = _clean_str(func.get("periodicity"))
    trigger = _clean_str(func.get("triggerAction"))
    action = _clean_str(func.get("userAction"))
    if tool:
        known_facts["workLocation"] = tool
    if periodicity:
        known_facts["frequency"] = periodicity
    if trigger:
        known_facts["trigger"] = trigger
    if action:
        known_facts["steps"] = [action]
    return {
        "id": process_id,
        "title": _clean_str(func.get("title")),
        "actor": _clean_str(func.get("actor")),
        "roleStatus": _normalize_role_status(func.get("roleStatus")),
        "sourceRefs": _clean_source_refs(func.get("sourceRefs")),
        "knownFacts": known_facts,
        "unknowns": _unknowns_from_function(func),
        "askedQuestions": [],
        "currentQuestion": {},
        "_fromFunction": True,
    }


def _merge_process(state: dict[str, Any], incoming: dict[str, Any]) -> None:
    if not incoming:
        return
    from_function = bool(incoming.get("_fromFunction"))
    clean_incoming = {key: value for key, value in incoming.items() if not key.startswith("_")}
    existing = _find_process(state.get("processes") or [], incoming)
    if existing is None:
        state.setdefault("processes", []).append(clean_incoming)
        return
    for key in ("title", "actor"):
        value = _clean_str(incoming.get(key))
        if not value:
            continue
        if key == "title" and _is_internal_process_label(value):
            continue
        existing[key] = value
    incoming_role = _normalize_role_status(incoming.get("roleStatus"))
    _apply_incoming_role_status(existing, incoming_role)
    refs = _clean_source_refs(incoming.get("sourceRefs"))
    if refs:
        current = _clean_source_refs(existing.get("sourceRefs"))
        existing["sourceRefs"] = current + [ref for ref in refs if ref not in current]
    existing_facts = existing.setdefault("knownFacts", {})
    for key, value in (incoming.get("knownFacts") or {}).items():
        if isinstance(value, list):
            current = _clean_list(existing_facts.get(key))
            existing_facts[key] = current + [item for item in _clean_list(value) if item not in current]
        else:
            text = _clean_str(value)
            if text:
                existing_facts[key] = text
    incoming_unknowns = _normalize_unknowns(incoming.get("unknowns"))
    if from_function:
        existing["unknowns"] = [
            item
            for item in _normalize_unknowns(existing.get("unknowns"))
            if _clean_str(item.get("source")) != "functionGaps"
        ]
    if incoming_unknowns:
        existing["unknowns"] = _merge_unknowns(existing.get("unknowns"), incoming_unknowns)
    incoming_questions = _normalize_questions(incoming.get("askedQuestions"))
    if incoming_questions:
        existing["askedQuestions"] = _merge_questions(existing.get("askedQuestions"), incoming_questions)
    if isinstance(incoming.get("currentQuestion"), dict) and incoming["currentQuestion"]:
        existing["currentQuestion"] = incoming["currentQuestion"]


def _find_process(processes: list[Any], incoming: dict[str, Any]) -> dict[str, Any] | None:
    incoming_id = _clean_str(incoming.get("id"))
    incoming_title = _clean_str(incoming.get("title")).lower()
    for item in processes:
        if not isinstance(item, dict):
            continue
        if incoming_id and _clean_str(item.get("id")) == incoming_id:
            return item
        if incoming_title and _clean_str(item.get("title")).lower() == incoming_title:
            return item
    return None


def _merge_unknowns(current: Any, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = _normalize_unknowns(current)
    seen = {(_clean_str(item.get("field")), _fold(_clean_str(item.get("reason") or item.get("question")))) for item in out}
    for item in incoming:
        key = (_clean_str(item.get("field")), _fold(_clean_str(item.get("reason") or item.get("question"))))
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out[-40:]


def _merge_questions(current: Any, incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = _normalize_questions(current)
    seen = {(_clean_str(item.get("field")), _fold(_clean_str(item.get("message")))) for item in out}
    for item in incoming:
        key = (_clean_str(item.get("field")), _fold(_clean_str(item.get("message"))))
        if key not in seen:
            out.append(item)
            seen.add(key)
    return out[-40:]


def _unknowns_from_function(func: dict[str, Any]) -> list[dict[str, Any]]:
    unknowns: list[dict[str, Any]] = []
    for field in _open_gaps(func):
        unknowns.append(
            {
                "id": f"u{len(unknowns) + 1}",
                "field": _canonical_gap(field),
                "reason": "Недостаточно данных для исполнимого описания процесса.",
                "question": "",
                "critical": True,
                "source": "functionGaps",
            }
        )
    return unknowns


def _open_gaps(func: dict[str, Any], *, position: str = "") -> list[str]:
    if _role_status(func) == ROLE_FOREIGN:
        return []
    if position and _role_status(func) != ROLE_BELONGS:
        return ["roleStatus"]
    gaps: list[str] = []
    for field in ("tool", "periodicity", "triggerAction", "userAction"):
        value = _clean_str(func.get(field))
        if _is_missing(value):
            gaps.append(field)
            continue
        if field == "tool" and _is_vague_work_location(value):
            gaps.append(field)
        elif field == "triggerAction" and _is_vague_trigger(value):
            gaps.append(field)
        elif field == "userAction" and _is_vague_user_action(value):
            gaps.append(field)
    return gaps


def _canonical_gap(value: Any) -> str:
    text = _clean_str(value).strip()
    folded = _fold(text)
    if folded in {"tool", "instrument", "system", "channel", "place", "location", "worklocation", "datasources", "readwritesources"}:
        return "tool"
    if folded in {"object", "objects", "records", "forms", "registers", "entity", "entities"}:
        return "tool"
    if folded in {"frequency", "periodicity", "cadence", "schedule"}:
        return "periodicity"
    if folded in {"deadline", "deadlines", "duedate", "timing", "срок", "сроки"}:
        return "deadlines"
    if folded in {"input", "inputs"}:
        return "inputs"
    if folded in {"output", "outputs", "result", "results"}:
        return "outputs"
    if folded in {"trigger", "start event", "startevent", "condition"}:
        return "triggerAction"
    if folded in {"steps", "actions", "procedure", "useraction", "user action"}:
        return "userAction"
    if folded in {"role", "rolestatus", "role status"}:
        return "roleStatus"
    return text


def _is_missing(value: str) -> bool:
    return value.strip().lower() in _UNKNOWN_VALUES


def _is_vague_work_location(value: str) -> bool:
    text = _fold(value)
    if not text:
        return True
    if any(marker in text for marker in _WORK_LOCATION_OBJECT_MARKERS):
        return False
    words = re.findall(r"[a-zA-Zа-яА-ЯёЁ0-9]+", text)
    specific_words = [word for word in words if word not in _GENERIC_WORK_LOCATION_WORDS and len(word) > 2]
    if len(specific_words) >= 2:
        return False
    if any(sep in value for sep in ("/", "\\", ":", ">", "->")) and len(words) >= 2:
        return False
    return True


def _is_vague_trigger(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return True
    if any(re.search(pattern, text) for pattern in _VAGUE_TRIGGER_PATTERNS):
        return not any(marker in text for marker in _CONCRETE_ACTION_MARKERS)
    return False


def _is_vague_user_action(value: str) -> bool:
    text = value.strip().lower()
    if not text:
        return True
    if any(word in text for word in ("сообщ", "уведом", "контрол", "обеспеч")):
        return not any(marker in text for marker in _CONCRETE_ACTION_MARKERS)
    return False


def _question_for_gap(func: dict[str, Any], field: str, *, position: str = "") -> ReadyBlocker:
    title = _clean_str(func.get("title")) or "эта функция"
    if field == "roleStatus":
        role = position or "вашей должности"
        return ReadyBlocker(
            message=(
                f"Функция «{title}» в документе выглядит неоднозначно. "
                f"Она относится к должности «{role}»?"
            ),
            quick_answers=["Да, это моя обязанность", "Нет, другая роль", "Частично, уточню"],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
    if field == "tool":
        value = _clean_str(func.get("tool"))
        if value:
            message = (
                f"По функции «{title}» указан общий инструмент «{value}». "
                "Где именно пользователь работает: какой документ, реестр, форма, раздел, карточка или канал?"
            )
        else:
            message = f"По функции «{title}» не указан инструмент. Где пользователь выполняет это действие?"
        return ReadyBlocker(
            message=message,
            quick_answers=[],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
    if field == "periodicity":
        return ReadyBlocker(
            message=f"По функции «{title}» не указано, как часто она выполняется. Какая периодичность?",
            quick_answers=[],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
    if field == "triggerAction":
        return ReadyBlocker(
            message=(
                f"По функции «{title}» нужен конкретный триггер. Что именно происходит перед началом "
                "действия: какое письмо, файл, статус, время или сообщение запускает работу?"
            ),
            quick_answers=[],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
    return ReadyBlocker(
        message=f"По функции «{title}» не описано, что пользователь делает руками или в системе. Как выглядит действие?",
        quick_answers=[],
        function_id=_clean_str(func.get("id")),
        field=field,
    )


def _attach_answer_to_current_question(state: dict[str, Any], message: str) -> None:
    current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    answer = _clean_str(message)
    if not current or not answer:
        return
    current["answer"] = answer
    current["sufficiency"] = "pending"
    state["currentQuestion"] = current
    question_id = _clean_str(current.get("id"))
    for item in reversed(state.get("askedQuestions") or []):
        if not isinstance(item, dict):
            continue
        if question_id and _clean_str(item.get("id")) != question_id:
            continue
        item["answer"] = answer
        item["sufficiency"] = "pending"
        break


def _record_answer_sufficiency(state: dict[str, Any], answer_sufficiency: dict[str, Any]) -> None:
    state["answerSufficiency"] = answer_sufficiency
    state["answers"].append(answer_sufficiency)
    state["answers"] = state["answers"][-40:]
    current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    question_id = _clean_str(current.get("id"))
    for item in reversed(state.get("askedQuestions") or []):
        if not isinstance(item, dict):
            continue
        if question_id and _clean_str(item.get("id")) != question_id:
            continue
        item["sufficiency"] = answer_sufficiency.get("status") or ""
        item["answerSummary"] = answer_sufficiency.get("answerSummary") or ""
        item["missingFacts"] = answer_sufficiency.get("missingFacts") or []
        item["reason"] = answer_sufficiency.get("reason") or ""
        break
    if current:
        current["sufficiency"] = answer_sufficiency.get("status") or ""
        current["answerSummary"] = answer_sufficiency.get("answerSummary") or ""
        current["missingFacts"] = answer_sufficiency.get("missingFacts") or []
        current["reason"] = answer_sufficiency.get("reason") or ""
        state["currentQuestion"] = {} if answer_sufficiency.get("status") == "closed" else current


def _apply_progress_from_user_answer(
    state: dict[str, Any],
    *,
    answer_sufficiency: dict[str, Any],
    next_question: dict[str, Any],
) -> None:
    """Write closed answers into knownFacts so interview_progress moves forward."""
    current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    answer_text = _clean_str(current.get("answer"))
    summary = _clean_str(answer_sufficiency.get("answerSummary")) if answer_sufficiency else ""
    value = summary or answer_text
    if not value:
        return
    field = _progress_field_key(
        (answer_sufficiency or {}).get("field")
        or current.get("field")
        or current.get("intent")
        or current.get("missingFact")
    )
    if field not in _PROGRESS_REQUIRED_FACTS:
        return
    process_id = normalize_process_id(
        (answer_sufficiency or {}).get("processId")
        or (answer_sufficiency or {}).get("functionId")
        or current.get("processId")
        or current.get("functionId")
        or next_question.get("processId")
        or next_question.get("functionId")
        or current_interview_process_id(state)
    )
    status = _clean_str((answer_sufficiency or {}).get("status")).lower()
    next_field = _progress_field_key(next_question.get("targetFact") or next_question.get("field"))
    advanced = bool(next_field and next_field != field and answer_text)
    if status != "closed" and not advanced:
        return
    _set_process_fact(state, process_id=process_id, field=field, value=value)


def _set_process_fact(state: dict[str, Any], *, process_id: str, field: str, value: str) -> None:
    text = _clean_str(value)
    if not text or field not in _PROGRESS_REQUIRED_FACTS:
        return
    process = None
    for item in state.get("processes") or []:
        if not isinstance(item, dict):
            continue
        if normalize_process_id(item.get("id") or item.get("processId")) == process_id:
            process = item
            break
    if process is None and process_id:
        process = {
            "id": process_id,
            "title": "",
            "roleStatus": ROLE_BELONGS,
            "knownFacts": {},
            "unknowns": [],
            "askedQuestions": [],
        }
        state.setdefault("processes", []).append(process)
    if process is None:
        return
    facts = process.setdefault("knownFacts", {})
    if field in {"steps", "inputs", "outputs", "recipients", "controls", "exceptions", "objects"}:
        current = _clean_list(facts.get(field))
        if text not in current:
            facts[field] = current + [text]
    else:
        facts[field] = text
    mapped = _PROCESS_FIELD_TO_FUNCTION_FIELD.get(field)
    if mapped:
        for func in state.get("functions") or []:
            if not isinstance(func, dict):
                continue
            if normalize_process_id(func.get("id") or func.get("processId")) != process_id:
                continue
            if not _clean_str(func.get(mapped)):
                func[mapped] = text


def _fact_open_in_known_facts(facts: dict[str, Any], field: str) -> bool:
    value = facts.get(field)
    empty = value in (None, "", []) or (
        isinstance(value, list) and not any(str(item).strip() for item in value)
    )
    if empty:
        return True
    text = value if isinstance(value, str) else " ".join(str(item) for item in value if str(item).strip())
    if field == "workLocation" and _is_vague_work_location(text):
        return True
    if field == "steps" and _is_vague_user_action(text):
        return True
    return False


def _prune_filled_unknowns(process: dict[str, Any]) -> list[dict[str, Any]]:
    facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
    kept: list[dict[str, Any]] = []
    for item in _normalize_unknowns(process.get("unknowns")):
        field = _progress_field_key(item.get("field"))
        if field in _PROGRESS_REQUIRED_FACTS and not _fact_open_in_known_facts(facts, field):
            continue
        kept.append(item)
    return kept


def _answer_sufficiency_blocker(payload: dict[str, Any], state: Any) -> ReadyBlocker | None:
    answer_sufficiency = _extract_answer_sufficiency(payload)
    if not answer_sufficiency or answer_sufficiency.get("status") == "closed":
        return None
    interview = normalize_interview_state(state)
    field = _canonical_gap(
        answer_sufficiency.get("field")
        or (answer_sufficiency.get("missingFacts") or [""])[0]
        or _current_question_field(interview)
    )
    func = _function_for_question(interview, answer_sufficiency.get("functionId") or answer_sufficiency.get("processId"))
    if func is not None and field:
        return _question_for_gap(func, _function_field(field), position=_clean_str(interview.get("position")))
    current = interview.get("currentQuestion") if isinstance(interview.get("currentQuestion"), dict) else {}
    message = _clean_str(current.get("message"))
    if message:
        return ReadyBlocker(
            message=f"Ответ пока не закрывает вопрос. Уточните, пожалуйста: {message}",
            quick_answers=[],
            function_id=_clean_str(current.get("functionId")),
            field=_current_question_field(interview),
        )
    return None


def _current_question_blocker(state: Any) -> ReadyBlocker | None:
    interview = normalize_interview_state(state)
    current = interview.get("currentQuestion") if isinstance(interview.get("currentQuestion"), dict) else {}
    if not current:
        return None
    field = _function_field(current.get("field"))
    if not field:
        return None
    func = _function_for_question(interview, current.get("functionId") or current.get("processId"))
    if func is None:
        return None
    gaps = _open_gaps(func, position=_clean_str(interview.get("position")))
    if field in gaps:
        return _question_for_gap(func, field, position=_clean_str(interview.get("position")))
    return None


def _process_unknown_blocker(state: Any) -> ReadyBlocker | None:
    interview = normalize_interview_state(state)
    for process in interview.get("processes") or []:
        if not isinstance(process, dict) or _role_status(process) == ROLE_FOREIGN:
            continue
        for unknown in _normalize_unknowns(process.get("unknowns")):
            if not bool(unknown.get("critical")):
                continue
            field = _function_field(unknown.get("field"))
            func = _function_for_question(interview, process.get("id"))
            if func is not None and field:
                return _question_for_gap(func, field, position=_clean_str(interview.get("position")))
            message = _clean_str(unknown.get("question") or unknown.get("reason"))
            if message:
                return ReadyBlocker(
                    message=message,
                    quick_answers=[],
                    function_id=_clean_str(process.get("id")),
                    field=field,
                )
    return None


def _function_for_question(state: dict[str, Any], raw_id: Any) -> dict[str, Any] | None:
    target_id = _clean_str(raw_id)
    functions = [item for item in state.get("functions") or [] if isinstance(item, dict)]
    if target_id:
        for func in functions:
            if _clean_str(func.get("id")) == target_id:
                return func
    return functions[0] if len(functions) == 1 else None


def _current_question_field(state: dict[str, Any]) -> str:
    current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    return _canonical_gap(current.get("field") or current.get("intent"))


def _function_field(field: Any) -> str:
    canonical = _canonical_gap(field)
    return _PROCESS_FIELD_TO_FUNCTION_FIELD.get(canonical, canonical)


def _question_was_asked(state: dict[str, Any], *, message: str, function_id: str, field: str) -> bool:
    text = _clean_str(message)
    if not text:
        return False
    current_field = _function_field(field)
    current_function = _clean_str(function_id)
    for item in reversed(state.get("askedQuestions") or []):
        if not isinstance(item, dict):
            continue
        same_field = _function_field(item.get("field")) == current_field
        same_function = not current_function or _clean_str(item.get("functionId") or item.get("processId")) == current_function
        if same_field and same_function and _fold(_clean_str(item.get("message"))) == _fold(text):
            return True
    return False


def _prompt_state(state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(state)
    out["attachments"] = _prompt_attachments(out.get("attachments") or [])
    return out


def _prompt_attachment_refs(attachments: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in attachments:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "file")
        text = str(raw.get("text") or "")
        out.append(
            {
                "id": raw.get("id"),
                "name": name,
                "kind": raw.get("kind") or "text",
                "chars": len(text),
                "path": f"materials/{Path(name).name}",
            }
        )
    return out


def _clean_source_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for ref in value:
        if not isinstance(ref, dict):
            continue
        file_name = _clean_str(ref.get("file"))
        quote = _clean_str(ref.get("quote"))
        fragment_id = _clean_str(ref.get("fragmentId"))
        if not file_name and not quote and not fragment_id:
            continue
        item = dict(ref)
        item["file"] = file_name
        item["quote"] = quote
        if fragment_id:
            item["fragmentId"] = fragment_id
        out.append(item)
    return out


def _prompt_attachments(attachments: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    total = 0
    for raw in attachments:
        if not isinstance(raw, dict):
            continue
        text = str(raw.get("text") or "")
        remain = max(0, MAX_PROMPT_ATTACHMENT_CHARS - total)
        if remain <= 0:
            break
        if len(text) > remain:
            text = text[:remain] + "\n...[text truncated]"
        total += len(text)
        out.append(
            {
                "id": raw.get("id"),
                "name": raw.get("name"),
                "kind": raw.get("kind") or "text",
                "text": text,
            }
        )
    return out


def document_from_interview(state: Any, title: str = "") -> dict[str, Any]:
    interview = normalize_interview_state(state)
    sections: list[dict[str, Any]] = []
    index = 0
    processes = [
        item
        for item in interview.get("processes") or []
        if isinstance(item, dict) and _role_status(item) != ROLE_FOREIGN
    ]
    if processes:
        for process in processes:
            index += 1
            sections.append(_document_section_from_process(process, index=index))
        return {
            "title": _clean_str(title) or "Регламент",
            "sections": sections,
        }
    for func in interview.get("functions") or []:
        if not isinstance(func, dict):
            continue
        if _role_status(func) == ROLE_FOREIGN:
            continue
        index += 1
        heading = _clean_str(func.get("title")) or f"Функция {index}"
        paragraphs: list[str] = []
        items: list[str] = []
        actor = _clean_str(func.get("actor"))
        if actor:
            paragraphs.append(f"Исполнитель: {actor}")
        for key, label in (
            ("tool", "Инструмент"),
            ("periodicity", "Периодичность"),
            ("triggerAction", "Триггер"),
            ("userAction", "Действие пользователя"),
        ):
            value = _clean_str(func.get(key))
            if value:
                items.append(f"{label}: {value}")
        for ref in func.get("sourceRefs") or []:
            if not isinstance(ref, dict):
                continue
            quote = _clean_str(ref.get("quote"))
            source = _clean_str(ref.get("file"))
            if quote:
                items.append(f"Источник{f' ({source})' if source else ''}: {quote}")
        if heading or paragraphs or items:
            sections.append(
                {
                    "number": str(index),
                    "title": heading,
                    "paragraphs": paragraphs,
                    "items": items,
                }
            )
    return {
        "title": _clean_str(title) or "Регламент",
        "sections": sections,
    }


def _document_section_from_process(process: dict[str, Any], *, index: int) -> dict[str, Any]:
    heading = _clean_str(process.get("title")) or f"Процесс {index}"
    paragraphs: list[str] = []
    items: list[str] = []
    actor = _clean_str(process.get("actor"))
    if actor:
        paragraphs.append(f"Исполнитель: {actor}")
    facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
    for key, label in (
        ("inputs", "Входы"),
        ("workLocation", "Где выполняется"),
        ("objects", "Объекты работы"),
        ("frequency", "Периодичность"),
        ("trigger", "Триггер"),
        ("steps", "Действия"),
        ("outputs", "Результаты"),
        ("recipients", "Получатели"),
        ("controls", "Проверки"),
        ("exceptions", "Исключения"),
    ):
        value = facts.get(key)
        if isinstance(value, list):
            for item in _clean_list(value):
                items.append(f"{label}: {item}")
        elif _clean_str(value):
            items.append(f"{label}: {_clean_str(value)}")
    for ref in process.get("sourceRefs") or []:
        if not isinstance(ref, dict):
            continue
        quote = _clean_str(ref.get("quote"))
        source = _clean_str(ref.get("file"))
        if quote:
            items.append(f"Источник{f' ({source})' if source else ''}: {quote}")
    return {
        "number": str(index),
        "title": heading,
        "paragraphs": paragraphs,
        "items": items,
    }


def document_has_body(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    for section in _walk_document_sections(document.get("sections") or []):
        if not isinstance(section, dict):
            continue
        if (
            _clean_str(section.get("title"))
            or any(_clean_str(item) for item in section.get("paragraphs") or [])
            or any(_clean_str(item) for item in section.get("items") or [])
        ):
            return True
    return False


def document_has_full_text(document: Any) -> bool:
    if not isinstance(document, dict):
        return False
    sections = _walk_document_sections(document.get("sections") or [])
    body_lines = _document_body_lines(document)
    if not body_lines:
        return False
    if _looks_like_card_document(sections):
        return False
    labelled = sum(1 for line in body_lines if _looks_like_field_label(line))
    if labelled >= max(3, (len(body_lines) + 1) // 2):
        return False
    service_lines = sum(1 for line in body_lines if _looks_like_service_line(line))
    if service_lines >= 3:
        return False
    prose_lines = [
        line
        for line in body_lines
        if not _looks_like_field_label(line) and len(line.split()) >= 10
    ]
    prose_total = sum(len(line) for line in prose_lines)
    if prose_total < 240:
        return False
    return len(prose_lines) >= 2 or prose_total >= 360


def _looks_like_card_document(sections: list[dict[str, Any]]) -> bool:
    section_stats: list[tuple[int, int, bool, int]] = []
    for section in sections:
        paragraphs = [_clean_str(item) for item in section.get("paragraphs") or []]
        items = [
            _clean_str(item.get("text") if isinstance(item, dict) else item)
            for item in section.get("items") or []
        ]
        paragraphs = [item for item in paragraphs if item]
        items = [item for item in items if item]
        if not paragraphs and not items:
            continue
        lines = [*paragraphs, *items]
        has_service_line = any(_looks_like_service_line(line) for line in lines)
        word_count = sum(len(line.split()) for line in lines)
        section_stats.append((len(paragraphs), len(items), has_service_line, word_count))
    if len(section_stats) < 3:
        return False
    card_like = 0
    for paragraph_count, item_count, has_service_line, word_count in section_stats:
        if item_count > 0 and paragraph_count <= 2 and (has_service_line or word_count < 80):
            card_like += 1
    return card_like >= max(2, (len(section_stats) + 1) // 2)


def _walk_document_sections(sections: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(sections, list):
        return out
    for section in sections:
        if not isinstance(section, dict):
            continue
        out.append(section)
        for key in ("sections", "subsections", "children"):
            out.extend(_walk_document_sections(section.get(key)))
    return out


def _document_body_lines(document: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for section in _walk_document_sections(document.get("sections") or []):
        for paragraph in section.get("paragraphs") or []:
            text = _clean_str(paragraph)
            if text:
                out.append(text)
        for item in section.get("items") or []:
            text = _clean_str(item.get("text") if isinstance(item, dict) else item)
            if text:
                out.append(text)
    return out


def _looks_like_field_label(text: str) -> bool:
    folded = _fold(text)
    if _looks_like_service_line(text):
        return True
    if ":" not in folded:
        return False
    left = folded.split(":", 1)[0].strip(" -•")
    return left in _DOCUMENT_FIELD_LABELS


def _looks_like_service_line(text: str) -> bool:
    folded = _fold(text).lstrip(" -•")
    return any(
        folded == prefix
        or folded.startswith(f"{prefix}:")
        or folded.startswith(f"{prefix} ")
        or folded.startswith(f"{prefix}(")
        for prefix in _DOCUMENT_SERVICE_PREFIXES
    )


def _apply_role_answer(state: dict[str, Any], message: str) -> None:
    text = message.strip().lower()
    decided = ""
    if any(marker in text for marker in _ROLE_FOREIGN_MARKERS):
        decided = ROLE_FOREIGN
    elif "частично" in text:
        decided = ROLE_BELONGS
    elif any(marker in text for marker in _ROLE_BELONGS_MARKERS) or text in {"да", "относится"}:
        decided = ROLE_BELONGS
    if not decided:
        return

    current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    current_field = _progress_field_key(current.get("field") or current.get("intent"))
    target_id = normalize_process_id(current.get("processId") or current.get("functionId"))
    if current_field and current_field != "roleStatus":
        return

    targets: list[dict[str, Any]] = []
    if target_id:
        for item in state.get("processes") or []:
            if not isinstance(item, dict):
                continue
            if normalize_process_id(item.get("id") or item.get("processId")) == target_id:
                targets.append(item)
        for item in state.get("functions") or []:
            if not isinstance(item, dict):
                continue
            if normalize_process_id(item.get("id") or item.get("processId") or item.get("functionId")) == target_id:
                targets.append(item)
    if not targets:
        for item in state.get("processes") or []:
            if isinstance(item, dict) and _role_status(item) == ROLE_UNCLEAR:
                targets.append(item)
                break
    if not targets:
        for item in state.get("functions") or []:
            if isinstance(item, dict) and _role_status(item) == ROLE_UNCLEAR:
                targets.append(item)
                break
    if not targets:
        return

    for target in targets:
        target["roleStatus"] = decided
        target["roleConfirmedByUser"] = True
    if decided == ROLE_FOREIGN and target_id:
        selected = selected_process_ids(state)
        if target_id in selected:
            state["selectedProcessIds"] = [item for item in selected if item != target_id]


def _apply_incoming_role_status(existing: dict[str, Any], incoming_role: str) -> None:
    existing_role = _normalize_role_status(existing.get("roleStatus"))
    if bool(existing.get("roleConfirmedByUser")) and existing_role in {ROLE_BELONGS, ROLE_FOREIGN}:
        return
    if incoming_role in {ROLE_BELONGS, ROLE_FOREIGN}:
        existing["roleStatus"] = incoming_role
    elif incoming_role == ROLE_UNCLEAR and existing_role not in {ROLE_BELONGS, ROLE_FOREIGN}:
        existing["roleStatus"] = ROLE_UNCLEAR


def _role_status(func: dict[str, Any]) -> str:
    return _normalize_role_status(func.get("roleStatus")) or ROLE_UNCLEAR


def _normalize_role_status(value: Any) -> str:
    text = _clean_str(value).lower().replace(" ", "")
    if text in {ROLE_BELONGS, "yes", "own", "mine", "да"}:
        return ROLE_BELONGS
    if text in {ROLE_FOREIGN, "no", "other", "нет"}:
        return ROLE_FOREIGN
    if text in {ROLE_UNCLEAR, "unknown", "partial"}:
        return ROLE_UNCLEAR
    return ""


def _fold(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


def _is_generic_actor(actor: str) -> bool:
    folded = _fold(actor)
    return not folded or folded in _GENERIC_ACTORS


def _actors_match(actor: str, position: str) -> bool:
    left = _fold(actor)
    right = _fold(position)
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    left_parts = {part for part in left.split() if len(part) > 3}
    right_parts = {part for part in right.split() if len(part) > 3}
    return bool(left_parts and right_parts and left_parts <= right_parts)


def _resolve_role_status(func: dict[str, Any], position: str) -> str:
    current = _normalize_role_status(func.get("roleStatus"))
    if current in {ROLE_BELONGS, ROLE_FOREIGN}:
        return current
    if not position:
        return current or ROLE_UNCLEAR
    actor = _clean_str(func.get("actor"))
    if _actors_match(actor, position):
        return ROLE_BELONGS
    return ROLE_UNCLEAR


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, tuple, set)):
        return ""
    text = str(value).strip()
    if is_replacement_garbage(text):
        return ""
    return text
