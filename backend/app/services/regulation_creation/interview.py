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


@dataclass(slots=True)
class ReadyBlocker:
    message: str
    quick_answers: list[str]
    function_id: str = ""
    field: str = ""


def new_interview_state() -> dict[str, Any]:
    return {"version": 1, "attachments": [], "turns": [], "functions": [], "answers": []}


def normalize_interview_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return new_interview_state()
    state = deepcopy(raw)
    state.setdefault("version", 1)
    state.setdefault("attachments", [])
    state.setdefault("turns", [])
    state.setdefault("functions", [])
    state.setdefault("answers", [])
    if not isinstance(state["attachments"], list):
        state["attachments"] = []
    if not isinstance(state["turns"], list):
        state["turns"] = []
    if not isinstance(state["functions"], list):
        state["functions"] = []
    if not isinstance(state["answers"], list):
        state["answers"] = []
    return state


def append_user_turn(state: Any, message: str, attachments: list[dict]) -> dict[str, Any]:
    out = normalize_interview_state(state)
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
    return out


def merge_agent_payload(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    out = normalize_interview_state(state)
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
    for func in out["functions"]:
        func["openGaps"] = _open_gaps(func)
    return out


def build_creation_prompt(*, state: Any, message: str, initial: bool, force_create: bool) -> str:
    interview = normalize_interview_state(state)
    inventory = _prompt_state(interview)
    action = "начни" if initial else "продолжай"
    force = (
        "Пользователь запросил принудительное создание. Можно вернуть status='ready' по текущим "
        "проверенным данным, но нельзя выдавать предположения как факты."
        if force_create
        else "Не возвращай status='ready', пока у каждой функции нет закрытых обязательных полей."
    )
    return (
        f"Ты помогаешь создать точный регламент действий пользователя. {action.capitalize()} интервью.\n"
        "Работай только по текстам приложенных файлов и ответам пользователя. Не используй шаблоны, "
        "эталоны и типовые догадки как содержание регламента.\n"
        "Если приложено несколько файлов, анализируй их вместе и не теряй ранее приложенные файлы.\n"
        "Сначала извлеки все функции, которые прописаны именно для пользователя или его должности. "
        "Чужие роли включай только как получателей, согласующих или источники входов.\n"
        "По каждой функции должны быть явно закрыты четыре поля: tool, periodicity, triggerAction, "
        "userAction.\n"
        "- tool: в какой системе, файле, канале или инструменте пользователь работает.\n"
        "- periodicity: как часто или с какой периодичностью выполняется действие.\n"
        "- triggerAction: конкретное наблюдаемое событие или действие, после которого начинается работа.\n"
        "- userAction: что именно делает пользователь руками или в системе.\n"
        "Триггер не может быть общей формулировкой. 'Сообщить за 2 часа до', 'уведомить заранее', "
        "'контролировать сроки', 'по мере необходимости' не закрывают триггер. В таких случаях спроси, "
        "что именно происходит: пришло письмо, появился файл, наступило время, изменился статус, "
        "руководитель написал в чат, пользователь открыл систему и т.п.\n"
        "Если не хватает данных, задай ровно один следующий вопрос по одной функции и одному полю. "
        "Не предлагай пользователю подтвердить выдуманный ответ. quickAnswers должны быть 2-6 "
        "конкретными вариантами рабочего поведения, без вариантов 'Оставить' и 'Переделать'.\n"
        f"{force}\n"
        "Ответ всегда строго JSON без markdown. Контракт:\n"
        "{\n"
        '  "status": "need_more|ready",\n'
        '  "message": "один вопрос или сообщение о готовности",\n'
        '  "positions": ["..."],\n'
        '  "quickAnswers": ["вариант 1", "вариант 2"],\n'
        '  "interview": {\n'
        '    "functions": [\n'
        "      {\n"
        '        "id": "f1",\n'
        '        "title": "короткое название функции",\n'
        '        "actor": "должность пользователя",\n'
        '        "sourceRefs": [{"file": "имя файла", "quote": "цитата"}],\n'
        '        "tool": "инструмент или система",\n'
        '        "periodicity": "как часто",\n'
        '        "triggerAction": "конкретное событие или действие запуска",\n'
        '        "userAction": "что пользователь делает",\n'
        '        "openGaps": ["tool|periodicity|triggerAction|userAction"]\n'
        "      }\n"
        "    ]\n"
        "  },\n"
        '  "document": {"title": "", "sections": [{"number": "1", "title": "", "paragraphs": [], "items": []}]}\n'
        "}\n"
        "Текущее постоянное состояние интервью:\n"
        f"{json.dumps(inventory, ensure_ascii=False, indent=2)}\n"
        f"Последний ответ пользователя: {message.strip()}"
    )


def ready_blocker(payload: dict[str, Any], state: Any) -> ReadyBlocker | None:
    if payload.get("status") != "ready":
        return None
    interview = merge_agent_payload(state, payload)
    functions = [item for item in interview.get("functions") or [] if isinstance(item, dict)]
    if not functions:
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
    for func in functions:
        gaps = _open_gaps(func)
        if gaps:
            field = gaps[0]
            return _question_for_gap(func, field)
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


def _normalize_function(raw: dict[str, Any], *, fallback_index: int) -> dict[str, Any]:
    title = _clean_str(raw.get("title") or raw.get("name") or raw.get("description"))
    func_id = _clean_str(raw.get("id") or raw.get("functionId")) or f"f{fallback_index}"
    if not title and not func_id:
        return {}
    item = {
        "id": func_id,
        "title": title or func_id,
        "actor": _clean_str(raw.get("actor") or raw.get("position")),
        "sourceRefs": raw.get("sourceRefs") if isinstance(raw.get("sourceRefs"), list) else [],
        "tool": _field_value(raw, "tool"),
        "periodicity": _field_value(raw, "periodicity"),
        "triggerAction": _field_value(raw, "triggerAction"),
        "userAction": _field_value(raw, "userAction"),
    }
    open_gaps = raw.get("openGaps")
    item["openGaps"] = [str(gap) for gap in open_gaps] if isinstance(open_gaps, list) else []
    return item


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
    refs = incoming.get("sourceRefs") if isinstance(incoming.get("sourceRefs"), list) else []
    if refs:
        current = existing.get("sourceRefs") if isinstance(existing.get("sourceRefs"), list) else []
        existing["sourceRefs"] = current + [ref for ref in refs if ref not in current]


def _open_gaps(func: dict[str, Any]) -> list[str]:
    gaps: list[str] = []
    for field in ("tool", "periodicity", "triggerAction", "userAction"):
        value = _clean_str(func.get(field))
        if _is_missing(value):
            gaps.append(field)
            continue
        if field == "triggerAction" and _is_vague_trigger(value):
            gaps.append(field)
        elif field == "userAction" and _is_vague_user_action(value):
            gaps.append(field)
    return gaps


def _is_missing(value: str) -> bool:
    return value.strip().lower() in _UNKNOWN_VALUES


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


def _question_for_gap(func: dict[str, Any], field: str) -> ReadyBlocker:
    title = _clean_str(func.get("title")) or "эта функция"
    if field == "tool":
        return ReadyBlocker(
            message=f"По функции «{title}» не указан инструмент. Где пользователь выполняет это действие?",
            quick_answers=["Outlook", "1C", "Excel-файл", "Корпоративная папка", "Рабочий чат", "Другое"],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
    if field == "periodicity":
        return ReadyBlocker(
            message=f"По функции «{title}» не указано, как часто она выполняется. Какая периодичность?",
            quick_answers=[
                "Каждый рабочий день",
                "Раз в неделю",
                "Раз в месяц",
                "При каждом входящем запросе",
                "По календарю события",
                "Другая",
            ],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
    if field == "triggerAction":
        return ReadyBlocker(
            message=(
                f"По функции «{title}» нужен конкретный триггер. Что именно происходит перед началом "
                "действия: какое письмо, файл, статус, время или сообщение запускает работу?"
            ),
            quick_answers=[
                "Приходит письмо в Outlook",
                "Появляется файл в папке",
                "Наступает заданное время",
                "Меняется статус в 1C",
                "Руководитель пишет в чат",
                "Другой конкретный триггер",
            ],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
    return ReadyBlocker(
        message=f"По функции «{title}» не описано, что пользователь делает руками или в системе. Как выглядит действие?",
        quick_answers=[
            "Открывает карточку и меняет статус",
            "Отправляет письмо",
            "Заполняет Excel-файл",
            "Загружает документ в папку",
            "Пишет сообщение в чат",
            "Другое действие",
        ],
        function_id=_clean_str(func.get("id")),
        field=field,
    )


def _prompt_state(state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(state)
    out["attachments"] = _prompt_attachments(out.get("attachments") or [])
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


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, tuple, set)):
        return ""
    return str(value).strip()
