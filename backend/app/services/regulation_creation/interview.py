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
    "чужая роль",
)


def new_interview_state() -> dict[str, Any]:
    return {
        "version": 1,
        "position": "",
        "sdk_agent_id": "",
        "attachments": [],
        "turns": [],
        "functions": [],
        "answers": [],
    }


def normalize_interview_state(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return new_interview_state()
    state = deepcopy(raw)
    state.setdefault("version", 1)
    state.setdefault("position", "")
    state.setdefault("sdk_agent_id", "")
    state.setdefault("attachments", [])
    state.setdefault("turns", [])
    state.setdefault("functions", [])
    state.setdefault("answers", [])
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
    if not isinstance(state["answers"], list):
        state["answers"] = []
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
    _apply_role_answer(out, message)
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
    position = _clean_str(out.get("position"))
    for func in out["functions"]:
        func["roleStatus"] = _resolve_role_status(func, position)
        func["openGaps"] = _open_gaps(func, position=position)
        func["sourceRefs"] = _clean_source_refs(func.get("sourceRefs"))
    return out


def creation_system_rules(*, force_create: bool = False) -> str:
    force = (
        "Пользователь запросил принудительное создание. Можно вернуть status='ready' по текущим "
        "проверенным данным, но нельзя выдавать предположения как факты."
        if force_create
        else "Не возвращай status='ready', пока у каждой функции должности нет закрытых обязательных полей."
    )
    return (
        "Ты помогаешь создать точный регламент действий пользователя. Продолжай интервью.\n"
        "Работай только по текстам приложенных файлов и ответам пользователя. Не используй шаблоны, "
        "эталоны и типовые догадки как содержание регламента.\n"
        "Если приложено несколько файлов, анализируй их вместе и не теряй ранее приложенные файлы.\n"
        "Сначала извлеки функциональные блоки из документов. Для каждого блока определи roleStatus: "
        "belongs (это обязанность указанной должности), foreign (другая роль) или unclear (сомнение).\n"
        "Если исполнитель в тексте не указан, указан общо (подразделение, ответственные) или не "
        "совпадает с должностью пользователя, roleStatus=unclear и сначала спроси, относится ли "
        "этот блок к должности пользователя. Не заполняй tool/periodicity/triggerAction/userAction, "
        "пока принадлежность не подтверждена.\n"
        "Чужие роли (foreign) не включай в регламент, только как получателей или источники входов.\n"
        "По каждой функции со статусом belongs должны быть закрыты четыре поля: tool, periodicity, "
        "triggerAction, userAction.\n"
        "- tool: в какой системе, файле, канале или инструменте пользователь работает.\n"
        "- periodicity: как часто или с какой периодичностью выполняется действие.\n"
        "- triggerAction: конкретное наблюдаемое событие или действие, после которого начинается работа.\n"
        "- userAction: что именно делает пользователь руками или в системе.\n"
        "Триггер не может быть общей формулировкой. 'Сообщить за 2 часа до', 'уведомить заранее', "
        "'контролировать сроки', 'по мере необходимости' не закрывают триггер.\n"
        "Если не хватает данных, задай ровно один следующий вопрос по одной функции и одному полю. "
        "Сначала закрывай roleStatus, затем остальные поля.\n"
        "Не предлагай пользователю подтвердить выдуманный ответ. quickAnswers должны быть 2-6 "
        "конкретными вариантами, без вариантов 'Оставить' и 'Переделать'.\n"
        "Пока status='need_more', не пиши полный document и не повторяй весь список функций. "
        "В interview.functions верни только новую или изменённую функцию. "
        "Сначала сформулируй короткий вопрос в message, затем компактный JSON.\n"
        "Когда все обязательные поля закрыты и можно вернуть status='ready', document обязателен. "
        "Его должен написать Cursor SDK как самостоятельный регламент процесса: связный документ, "
        "понятный без истории чата, без технического дампа полей interview. "
        "В документе простым деловым языком объясни, для чего выполняется процесс, где его границы, "
        "кто исполняет, какие входы используются, какое наблюдаемое событие или расписание запускает "
        "работу, как пользователь выполняет процесс по шагам, какой результат создаётся, кому он "
        "передаётся, какие исключения и эскалации подтверждены. "
        "Не ограничивайся четырьмя полями interview: перечитай materials/* и вынеси в документ "
        "релевантное содержание файлов пользователя - правила, условия, сроки, участников, входные "
        "и выходные артефакты, ограничения, исключения и подтверждённые формулировки. "
        "Документ должен читаться как нормальный деловой регламент, с абзацами и переходами между "
        "мыслями, а не как анкета или таблица фактов. "
        "interview.functions - это рабочая инвентаризация фактов для интервью, а не структура "
        "будущего документа. document.sections - только технический контейнер для DOCX, не шаблон "
        "разделов. Не делай 'одна функция = один раздел' и не повторяй в каждом разделе схему "
        "'Основание -> список действий -> Предположение'. Объединяй связанные факты в цельное "
        "описание процесса; списки используй только для реального порядка действий, а не вместо "
        "связного объяснения. "
        "Не используй фиксированный шаблон глав и не копируй лейблы вида 'Инструмент:', "
        "'Периодичность:', 'Триггер:', 'Действие пользователя:' как тело документа. "
        "Структуру разделов выбирай по фактическому процессу. Факты бери только из interview.json, "
        "materials/* и ответов пользователя; неизвестное не выдумывай и не оформляй как факт. "
        "Если в interview.json есть document_write_required=true, не задавай новый вопрос: "
        "сразу верни status='ready' и перепиши document в полноценный самостоятельный текст.\n"
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
        '        "actor": "должность из документа",\n'
        '        "roleStatus": "belongs|foreign|unclear",\n'
        '        "sourceRefs": [{"file": "имя файла", "quote": "цитата"}],\n'
        '        "tool": "инструмент или система",\n'
        '        "periodicity": "как часто",\n'
        '        "triggerAction": "конкретное событие или действие запуска",\n'
        '        "userAction": "что пользователь делает",\n'
        '        "openGaps": ["roleStatus|tool|periodicity|triggerAction|userAction"]\n'
        "      }\n"
        "    ]\n"
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
        else ""
    )
    return (
        f"{action} интервью.\n"
        f"{creation_system_rules(force_create=force_create)}\n"
        f"{files_hint}"
        "Текущее постоянное состояние интервью:\n"
        f"{json.dumps(inventory, ensure_ascii=False, indent=2)}\n"
        f"Последний ответ пользователя: {message.strip()}"
    )


def build_followup_creation_prompt(*, message: str, force_create: bool) -> str:
    force = (
        "Пользователь запросил принудительное создание. Можно вернуть status='ready' по текущим данным."
        if force_create
        else "Не возвращай status='ready', пока есть unclear roleStatus или открытые поля belongs-функций."
    )
    return (
        "Продолжи то же интервью. История диалога уже у тебя. "
        "Прочитай обновлённый interview.json в рабочей папке.\n"
        f"{force}\n"
        f"Последний ответ пользователя: {message.strip()}\n"
        "Если в interview.json есть document_write_required=true, не задавай новый вопрос: "
        "верни status='ready' и полный document как самостоятельный связный регламент процесса. "
        "Иначе ответ строго JSON: status, message, quickAnswers и только изменённая функция. "
        "document оставляй пустым, пока status не ready. При status='ready' document обязателен: "
        "это должен быть полный деловой текст, а не список полей interview. Вынеси в него "
        "релевантное содержание материалов пользователя, подтверждённое файлами или ответами. "
        "Не используй interview.functions как оглавление и не пиши одинаковые карточки функций "
        "с повтором 'Основание' и 'Предположение' в каждом блоке."
    )


def ready_blocker(payload: dict[str, Any], state: Any) -> ReadyBlocker | None:
    if payload.get("status") != "ready":
        return None
    interview = merge_agent_payload(state, payload)
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
    existing_role = _normalize_role_status(existing.get("roleStatus"))
    if incoming_role in {ROLE_BELONGS, ROLE_FOREIGN}:
        existing["roleStatus"] = incoming_role
    elif incoming_role == ROLE_UNCLEAR and existing_role not in {ROLE_BELONGS, ROLE_FOREIGN}:
        existing["roleStatus"] = ROLE_UNCLEAR
    refs = _clean_source_refs(incoming.get("sourceRefs"))
    if refs:
        current = _clean_source_refs(existing.get("sourceRefs"))
        existing["sourceRefs"] = current + [ref for ref in refs if ref not in current]


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


def _question_for_gap(func: dict[str, Any], field: str, *, position: str = "") -> ReadyBlocker:
    title = _clean_str(func.get("title")) or "эта функция"
    if field == "roleStatus":
        role = position or "вашей должности"
        return ReadyBlocker(
            message=(
                f"Функция «{title}» в документе выглядит неоднозначно. "
                f"Она относится к должности «{role}»?"
            ),
            quick_answers=[
                "Да, это моя обязанность",
                "Нет, другая роль",
                "Частично, уточню",
            ],
            function_id=_clean_str(func.get("id")),
            field=field,
        )
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
        if not file_name and not quote:
            continue
        item = dict(ref)
        item["file"] = file_name
        item["quote"] = quote
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
    target = None
    for func in state.get("functions") or []:
        if isinstance(func, dict) and _role_status(func) == ROLE_UNCLEAR:
            target = func
            break
    if target is None:
        return
    text = message.strip().lower()
    if any(marker in text for marker in _ROLE_FOREIGN_MARKERS):
        target["roleStatus"] = ROLE_FOREIGN
        return
    if "частично" in text:
        target["roleStatus"] = ROLE_BELONGS
        return
    if any(marker in text for marker in _ROLE_BELONGS_MARKERS) or text in {"да", "относится"}:
        target["roleStatus"] = ROLE_BELONGS


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
