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

_ANSWER_SUFFICIENCY_STATUSES = {"closed", "partial", "not_answered"}

_PROCESS_FACT_ALIASES = {
    "inputs": ("inputs", "input", "sourceInputs", "входы", "исходные данные"),
    "workLocation": (
        "workLocation",
        "tool",
        "instrument",
        "system",
        "channel",
        "place",
        "location",
        "где работает",
        "место работы",
        "система",
    ),
    "objects": ("objects", "records", "forms", "registers", "entities", "объекты", "реестры", "формы"),
    "trigger": ("trigger", "triggerAction", "startEvent", "condition", "триггер", "условие запуска"),
    "frequency": ("frequency", "periodicity", "cadence", "schedule", "периодичность"),
    "steps": ("steps", "actions", "userAction", "procedure", "шаги", "действия"),
    "outputs": ("outputs", "result", "artifacts", "результаты", "выходы"),
    "recipients": ("recipients", "receivers", "toWhom", "получатели", "кому передается"),
    "controls": ("controls", "checks", "criteria", "проверки", "контроль"),
    "exceptions": ("exceptions", "escalations", "risks", "исключения", "эскалации"),
}

_PROCESS_FIELD_TO_FUNCTION_FIELD = {
    "workLocation": "tool",
    "objects": "tool",
    "frequency": "periodicity",
    "trigger": "triggerAction",
    "steps": "userAction",
}

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
    from app.services.regulation_creation.pipeline import default_pipeline

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
        "pipeline": default_pipeline(),
    }


def normalize_interview_state(raw: Any) -> dict[str, Any]:
    from app.services.regulation_creation.pipeline import normalize_pipeline

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
    state["pipeline"] = normalize_pipeline(state.get("pipeline"))
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
    from app.services.regulation_creation.pipeline import apply_round_answers, mark_upload_received

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
    _attach_answer_to_current_question(out, message)
    _apply_role_answer(out, message)
    _apply_explicit_unknown_answer(out, message)
    out = mark_upload_received(out)
    if message.strip():
        out = apply_round_answers(out, free_message=message.strip())
    return out


def merge_agent_payload(state: Any, payload: dict[str, Any]) -> dict[str, Any]:
    from app.services.regulation_creation.pipeline import merge_pipeline_payload

    out = normalize_interview_state(state)
    answer_sufficiency = _extract_answer_sufficiency(payload)
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
        process["unknowns"] = _normalize_unknowns(process.get("unknowns"))
    out = merge_pipeline_payload(out, payload)
    return out


def creation_interview_rules(*, force_create: bool = False) -> str:
    force = (
        "Пользователь запросил принудительное создание: можно вернуть status='ready' по проверенным данным "
        "без выдумок."
        if force_create
        else (
            "Не возвращай status='ready', пока по каждому процессу должности нельзя написать "
            "исполняемый алгоритм без критичных неизвестных."
        )
    )
    return (
        "Ты ведёшь короткое процессное интервью для регламента. Отвечай сразу.\n"
        "Не пиши длинные рассуждения: сначала короткий вопрос в message, затем компактный JSON.\n"
        "Работай только по текстам файлов и ответам пользователя. Не выдумывай факты.\n"
        "Если файлов несколько — учитывай все. Извлеки функциональные блоки и для каждого roleStatus: "
        "belongs / foreign / unclear.\n"
        "Пока roleStatus не belongs, не заполняй tool/periodicity/triggerAction/userAction — сначала спроси "
        "принадлежность. foreign не включай в регламент (только как источники/получатели).\n"
        "По belongs закрой четыре поля: tool, periodicity, triggerAction, userAction.\n"
        "Главная модель — interview.processes (knownFacts, unknowns, askedQuestions). "
        "interview.functions — краткий срез.\n"
        "Оцени последний ответ в answerSufficiency: closed|partial|not_answered. "
        "Если partial/not_answered — один углубляющий вопрос по тому же процессу/полю, не перескакивай.\n"
        "За один ход: ровно один вопрос, одно поле, одна функция. Не повторяй askedQuestions.\n"
        "Триггер не закрывают общие фразы («при необходимости», «своевременно», «контролировать»).\n"
        "quickAnswers: 2–6 конкретных вариантов, без «Оставить»/«Переделать».\n"
        "Пока status='need_more': не пиши document, в interview.functions только новая/изменённая функция.\n"
        f"{force}\n"
        "Ответ строго JSON без markdown:\n"
        "{\n"
        '  "status": "need_more|ready",\n'
        '  "message": "один короткий вопрос",\n'
        '  "positions": ["..."],\n'
        '  "quickAnswers": ["вариант 1", "вариант 2"],\n'
        '  "answerSufficiency": {\n'
        '    "status": "closed|partial|not_answered",\n'
        '    "processId": "f1",\n'
        '    "field": "tool|periodicity|triggerAction|userAction|roleStatus",\n'
        '    "answerSummary": "...",\n'
        '    "missingFacts": ["..."],\n'
        '    "reason": "..."\n'
        "  },\n"
        '  "interview": {\n'
        '    "processes": [{"id":"f1","title":"...","actor":"...","roleStatus":"belongs|foreign|unclear",'
        '"knownFacts":{},"unknowns":[],"askedQuestions":[]}],\n'
        '    "functions": [{"id":"f1","title":"...","roleStatus":"...","tool":"","periodicity":"",'
        '"triggerAction":"","userAction":"","openGaps":[]}]\n'
        "  },\n"
        '  "document": {}\n'
        "}\n"
        "document заполняй только при status='ready' (см. правила финализации в отдельном запросе)."
    )


def creation_document_rules(*, force_create: bool = False) -> str:
    force = (
        "Пользователь запросил принудительное создание. Можно вернуть status='ready' по текущим "
        "проверенным данным, но нельзя выдавать предположения как факты."
        if force_create
        else "Верни status='ready' и полный document только если критичные unknowns закрыты."
    )
    return (
        "Сейчас финализация: верни status='ready' и полный document как самостоятельный регламент.\n"
        "Не задавай новый вопрос. Не копируй историю чата — пиши нормативный текст.\n"
        "Факты только из interview.json, materials/* и ответов пользователя.\n"
        "Шаблон СТО-34-003, разделы document.sections строго в порядке:\n"
        "1 Назначение и область применения; 2 Нормативные ссылки; 3 Термины и определения; "
        "4 Сокращения; 5 Ответственность; 6 Организация работы; 7 Ресурсы; "
        "8 Документирование и архивирование; 9 Приложения.\n"
        "Раздел 6 — жёсткая последовательность: кто, что, кому, срок, форма. "
        "Таблицы в section.tables {headers, rows}. Подразделы 6.1/6.2 — в section.sections.\n"
        "Не своди документ к четырём полям interview. Сохрани детали из материалов.\n"
        "Запрещены заглушки и общие фразы без критерия.\n"
        f"{force}\n"
        "Ответ строго JSON: status='ready', message, interview (срез), полный document "
        "(title, code, version, year, meta, sections)."
    )


def creation_collect_rules() -> str:
    return (
        "Сейчас этап COLLECT: добираем обязательные факты только по выбранным процессам.\n"
        "Поля для закрытия: tool/workLocation, periodicity/frequency, triggerAction/trigger, userAction/steps.\n"
        "Не переходи к свободному раунду до закрытия этого минимума.\n"
        "За один ход: один процесс, одно поле, один конкретный вопрос.\n"
        "Ответ строго JSON: status='need_more', message, quickAnswers, roundQuestions=[], document={}."
    )


def creation_system_rules(
    *,
    force_create: bool = False,
    for_document: bool = False,
    stage: str = "",
    pipeline: dict[str, Any] | None = None,
) -> str:
    from app.services.regulation_creation.pipeline import (
        creation_extract_rules,
        creation_round_interview_rules,
        creation_select_rules,
        normalize_pipeline,
    )

    pipe = normalize_pipeline(pipeline or {"stage": stage})
    phase = str(pipe.get("interviewPhase") or stage or "")

    if for_document or force_create:
        if for_document:
            return creation_document_rules(force_create=force_create)
        return (
            f"{creation_round_interview_rules(force_create=True)}\n\n"
            f"{creation_document_rules(force_create=True)}"
        )
    if phase == "extract":
        return creation_extract_rules()
    if phase == "select":
        return creation_select_rules()
    if phase == "collect":
        return creation_collect_rules()
    return creation_round_interview_rules(force_create=force_create)


def build_creation_prompt(
    *,
    state: Any,
    message: str,
    initial: bool,
    force_create: bool,
    include_attachment_bodies: bool = True,
    for_document: bool = False,
) -> str:
    from app.services.regulation_creation.pipeline import normalize_pipeline, slice_materials_for_prompt

    interview = normalize_interview_state(state)
    pipeline = normalize_pipeline(interview.get("pipeline"))
    stage = str(pipeline.get("stage") or "upload")
    for_document = for_document or bool(interview.get("document_write_required")) or force_create
    inventory = _prompt_inventory_for_stage(interview, pipeline=pipeline, for_document=for_document)
    if not include_attachment_bodies:
        inventory["attachments"] = _prompt_attachment_refs(inventory.get("attachments") or [])
    elif stage in ("interview", "select") and not for_document:
        inventory["attachments"] = _prompt_attachments(slice_materials_for_prompt(interview, full=False))
    inventory["pipeline"] = pipeline
    action = "Начни" if initial else "Продолжай"
    files_hint = (
        "Тексты приложенных файлов уже лежат в рабочей папке: interview.json и materials/*.txt. "
        "Прочитай их оттуда. Не выдумывай содержание документов.\n"
        if not include_attachment_bodies
        else ""
    )
    speed = (
        ""
        if for_document
        else (
            "Скорость: ответь сразу. На extract — JSON процессов; "
            "на select — только список для выбора, без вопросов; "
            "на collect — один обязательный gap-вопрос; на interview — batch roundQuestions. "
            "Без длинного thinking.\n"
        )
    )
    stage_hint = (
        f"pipeline.stage={stage}, phase={pipeline.get('interviewPhase')}, round={pipeline.get('round')}, "
        f"questionsAskedTotal={pipeline.get('questionsAskedTotal')}.\n"
    )
    return (
        f"{action} интервью.\n"
        f"{speed}"
        f"{stage_hint}"
        f"{creation_system_rules(force_create=force_create, for_document=for_document, stage=stage, pipeline=pipeline)}\n"
        f"{files_hint}"
        "Текущее состояние интервью:\n"
        f"{json.dumps(inventory, ensure_ascii=False, indent=2)}\n"
        f"Последний ответ пользователя: {message.strip()}"
    )


def build_followup_creation_prompt(
    *,
    message: str,
    force_create: bool,
    for_document: bool = False,
    stage: str = "interview",
    pipeline: dict[str, Any] | None = None,
) -> str:
    from app.services.regulation_creation.pipeline import (
        MAX_QUESTIONS_PER_ROUND,
        creation_extract_rules,
        creation_round_interview_rules,
        creation_select_rules,
        normalize_pipeline,
    )

    phase = str(normalize_pipeline(pipeline or {"stage": stage}).get("interviewPhase") or stage)

    if for_document or force_create:
        return (
            "Продолжи интервью. История уже у тебя. Прочитай обновлённый interview.json.\n"
            f"{creation_document_rules(force_create=force_create)}\n"
            f"Последний ответ пользователя: {message.strip()}"
        )
    if phase == "extract":
        return (
            "Продолжи этап EXTRACT. Прочитай interview.json и materials.\n"
            f"{creation_extract_rules()}\n"
            f"Последний ответ пользователя: {message.strip()}"
        )
    if phase == "select":
        return (
            "Этап SELECT: пользователь ещё не подтвердил процессы.\n"
            f"{creation_select_rules()}\n"
            f"Последний ответ пользователя: {message.strip()}"
        )
    if phase == "collect":
        return (
            "Этап COLLECT: закрывай обязательные факты по выбранным процессам по одному gap за ход.\n"
            f"{creation_collect_rules()}\n"
            f"Последний ответ пользователя: {message.strip()}"
        )
    return (
        "Продолжи блочное интервью. Прочитай interview.json: answers, questionnaire, pipeline.\n"
        f"Сначала учти уже данные ответы, затем подготовь следующий roundQuestions "
        f"(до {MAX_QUESTIONS_PER_ROUND}).\n"
        f"{creation_round_interview_rules(force_create=force_create)}\n"
        f"Последний ответ пользователя: {message.strip()}\n"
        "document оставляй пустым, пока status не ready."
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
) -> tuple[dict[str, Any], str]:
    out = normalize_interview_state(state)
    text = _dedupe_question_text(out, message=message, function_id=function_id, field=field)
    question_id = f"q{len(out['askedQuestions']) + 1}"
    canonical_field = _canonical_gap(field)
    question = {
        "id": question_id,
        "message": text,
        "quickAnswers": list(quick_answers or []),
        "functionId": _clean_str(function_id),
        "processId": _clean_str(process_id or function_id),
        "field": canonical_field,
        "intent": _clean_str(intent) or canonical_field,
        "answer": "",
        "sufficiency": "pending",
        "missingFacts": [],
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
    from app.services.regulation_creation.pipeline import normalize_pipeline, round_gate

    interview = merge_agent_payload(state, payload)
    pipeline = normalize_pipeline(interview.get("pipeline"))
    gate = round_gate(pipeline=pipeline, force_create=False)
    if gate:
        return ReadyBlocker(
            message=gate,
            quick_answers=["Продолжить раунд", "Отвечу на вопросы", "Принудительно создать"],
            field="pipeline",
        )
    functions = [item for item in interview.get("functions") or [] if isinstance(item, dict)]
    position = _clean_str(interview.get("position"))
    owned = [item for item in functions if _role_status(item) != ROLE_FOREIGN]
    selected = set(pipeline.get("selectedProcessIds") or [])
    if selected:
        owned = [item for item in owned if _clean_str(item.get("id")) in selected] or owned
    if not owned:
        processes = [
            item
            for item in interview.get("processes") or []
            if isinstance(item, dict) and _role_status(item) != ROLE_FOREIGN
        ]
        if selected:
            processes = [item for item in processes if _clean_str(item.get("id")) in selected]
        if not processes:
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
        "title": title or process_id,
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
    existing_role = _normalize_role_status(existing.get("roleStatus"))
    if incoming_role in {ROLE_BELONGS, ROLE_FOREIGN}:
        existing["roleStatus"] = incoming_role
    elif incoming_role == ROLE_UNCLEAR and existing_role not in {ROLE_BELONGS, ROLE_FOREIGN}:
        existing["roleStatus"] = ROLE_UNCLEAR
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
        "title": _clean_str(func.get("title")) or process_id,
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
    if folded in {"tool", "instrument", "system", "channel", "place", "location", "worklocation"}:
        return "tool"
    if folded in {"object", "objects", "records", "forms", "registers", "entity", "entities"}:
        return "tool"
    if folded in {"frequency", "periodicity", "cadence", "schedule"}:
        return "periodicity"
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
            quick_answers=[
                "Да, это моя обязанность",
                "Нет, другая роль",
                "Частично, уточню",
            ],
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
            quick_answers=[
                "Реестр или журнал в системе",
                "Карточка документа",
                "Конкретный файл или папка",
                "Форма или раздел системы",
                "Рабочий чат или канал",
                "Уточню вручную",
            ],
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
            quick_answers=["Уточню конкретно", "Опишу шагами", "Укажу источник и результат"],
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
                    quick_answers=["Уточню", "Опишу шагами", "Неизвестно"],
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


def _dedupe_question_text(state: dict[str, Any], *, message: str, function_id: str, field: str) -> str:
    text = _clean_str(message)
    if not text:
        return text
    current_field = _function_field(field)
    current_function = _clean_str(function_id)
    current_signature = _question_signature(text)
    duplicate_count = 0
    for item in reversed(state.get("askedQuestions") or []):
        if not isinstance(item, dict):
            continue
        same_field = _function_field(item.get("field")) == current_field
        same_function = not current_function or _clean_str(item.get("functionId") or item.get("processId")) == current_function
        same_question = _question_signature(_clean_str(item.get("message"))) == current_signature
        if same_field and same_function and same_question:
            duplicate_count += 1
    if duplicate_count <= 0:
        return text
    return _escalate_duplicate_question(text=text, field=current_field, duplicate_count=duplicate_count)


def _escalate_duplicate_question(*, text: str, field: str, duplicate_count: int) -> str:
    field_hint = _duplicate_question_hint(field, duplicate_count)
    if duplicate_count == 1:
        return f"{text}\n\n{field_hint}"
    if duplicate_count == 2:
        return f"Нужна конкретика, чтобы закрыть пробел.\n{field_hint}\n\n{text}"
    return (
        "Ответ пока слишком общий. Дайте исполнимое описание шага.\n"
        f"{field_hint}\n"
        "Можно в формате: [где/объект] -> [действие] -> [результат]."
    )


def _duplicate_question_hint(field: str, duplicate_count: int) -> str:
    hint_map = {
        "tool": [
            "Укажите не только систему, а конкретный объект: файл/реестр/форма/карточка.",
            "Напишите точный путь или название объекта работы (пример: папка, файл Excel, карточка в 1С).",
        ],
        "triggerAction": [
            "Назовите наблюдаемое событие запуска: после чего именно начинается действие.",
            "Укажите конкретный триггер с условием (кто/что/когда инициирует действие).",
        ],
        "periodicity": [
            "Уточните периодичность: ежедневно/еженедельно/по событию + конкретное время или дедлайн.",
            "Нужна измеримая частота выполнения (без формулировок «по необходимости»).",
        ],
        "userAction": [
            "Опишите шаг руками: что открыть, что изменить, что сохранить/отправить.",
            "Дайте последовательность 2-4 шага в системе или файле, чтобы действие можно было повторить.",
        ],
    }
    variants = hint_map.get(field) or [
        "Добавьте конкретику по шагу: объект работы, действие пользователя и результат.",
        "Опишите этот шаг так, чтобы его можно было выполнить без догадок.",
    ]
    return variants[(max(1, duplicate_count) - 1) % len(variants)]


def _question_signature(text: str) -> str:
    folded = _fold(text)
    if not folded:
        return ""
    # Убираем переменные части формулировки, чтобы ловить "тот же смысл" вопроса.
    folded = re.sub(r"«[^»]+»", " ", folded)
    folded = re.sub(r'"[^"]+"', " ", folded)
    folded = re.sub(r"\bфункци[яи]\b\s+[a-zа-я0-9_-]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip()


def _apply_explicit_unknown_answer(state: dict[str, Any], message: str) -> None:
    current = state.get("currentQuestion") if isinstance(state.get("currentQuestion"), dict) else {}
    if not current:
        return
    field = _function_field(current.get("field"))
    if field not in {"tool", "periodicity", "triggerAction", "userAction"}:
        return
    answer = _fold(_clean_str(message))
    if not answer:
        return
    unknown_markers = (
        "нет данных",
        "не знаю",
        "неизвестно",
        "не могу уточнить",
        "уточню позже",
        "пока нет",
        "нет информации",
    )
    if not any(marker in answer for marker in unknown_markers):
        return
    func = _function_for_question(state, current.get("functionId") or current.get("processId"))
    if func is None:
        return
    placeholder = _tbd_value_for_field(field)
    func[field] = placeholder
    _set_process_fact_tbd(state, process_id=current.get("processId") or current.get("functionId"), field=field, value=placeholder)
    current["sufficiency"] = "closed"
    current["answerSummary"] = "Зафиксировано как TBD по явному ответу пользователя."
    current["missingFacts"] = []
    current["reason"] = "Пользователь подтвердил отсутствие данных на текущем этапе."
    question_id = _clean_str(current.get("id"))
    for item in reversed(state.get("askedQuestions") or []):
        if not isinstance(item, dict):
            continue
        if question_id and _clean_str(item.get("id")) != question_id:
            continue
        item["sufficiency"] = "closed"
        item["answerSummary"] = current["answerSummary"]
        item["missingFacts"] = []
        item["reason"] = current["reason"]
        break
    state["currentQuestion"] = {}


def _tbd_value_for_field(field: str) -> str:
    labels = {
        "tool": "<TBD: уточнить систему/объект работы>",
        "periodicity": "<TBD: уточнить периодичность>",
        "triggerAction": "<TBD: уточнить триггер запуска>",
        "userAction": "<TBD: уточнить действие пользователя>",
    }
    return labels.get(field, "<TBD: уточнить>")


def _set_process_fact_tbd(state: dict[str, Any], *, process_id: Any, field: str, value: str) -> None:
    target_id = _clean_str(process_id)
    canonical_process_field = {
        "tool": "workLocation",
        "periodicity": "frequency",
        "triggerAction": "trigger",
        "userAction": "steps",
    }.get(field, "")
    if not canonical_process_field:
        return
    for process in state.get("processes") or []:
        if not isinstance(process, dict):
            continue
        pid = _clean_str(process.get("id"))
        if target_id and pid != target_id:
            continue
        facts = process.setdefault("knownFacts", {})
        if canonical_process_field == "steps":
            steps = _clean_list(facts.get("steps"))
            if value not in steps:
                steps.append(value)
            facts["steps"] = steps
        else:
            facts[canonical_process_field] = value
        break


def _prompt_state(state: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(state)
    out["attachments"] = _prompt_attachments(out.get("attachments") or [])
    return out


def _prompt_inventory_for_stage(
    state: dict[str, Any],
    *,
    pipeline: dict[str, Any],
    for_document: bool,
) -> dict[str, Any]:
    if for_document:
        return _prompt_state(state)
    stage = str(pipeline.get("stage") or "")
    phase = str(pipeline.get("interviewPhase") or stage)
    if stage != "interview":
        return _prompt_state(state)
    selected = {
        _clean_str(item)
        for item in (pipeline.get("selectedProcessIds") or [])
        if _clean_str(item)
    }
    processes = [item for item in (state.get("processes") or []) if isinstance(item, dict)]
    if selected:
        processes = [item for item in processes if _clean_str(item.get("id")) in selected]
    out = {
        "version": state.get("version"),
        "position": state.get("position"),
        "pipeline": pipeline,
        "attachments": _prompt_attachments(state.get("attachments") or []),
        "turns": (state.get("turns") or [])[-6:],
        "answers": (state.get("answers") or [])[-20:],
        "askedQuestions": (state.get("askedQuestions") or [])[-20:],
        "currentQuestion": state.get("currentQuestion") or {},
    }
    if phase == "collect":
        out["processes"] = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "actor": item.get("actor"),
                "roleStatus": item.get("roleStatus"),
                "knownFacts": item.get("knownFacts") or {},
                "unknowns": item.get("unknowns") or [],
            }
            for item in processes
        ]
        out["functions"] = []
        return out
    out["processes"] = processes
    out["functions"] = [
        item
        for item in (state.get("functions") or [])
        if isinstance(item, dict)
        and (not selected or _clean_str(item.get("id") or item.get("processId")) in selected)
    ]
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
    sto_sections = (
        "Назначение и область применения",
        "Нормативные ссылки",
        "Термины и определения",
        "Сокращения",
        "Ответственность",
        "Организация работы",
        "Ресурсы",
        "Документирование и архивирование",
        "Приложения",
    )

    interview = normalize_interview_state(state)
    heading = _clean_str(title) or "Регламент"
    processes = [
        item
        for item in interview.get("processes") or []
        if isinstance(item, dict) and _role_status(item) != ROLE_FOREIGN
    ]
    functions = [
        item
        for item in interview.get("functions") or []
        if isinstance(item, dict) and _role_status(item) != ROLE_FOREIGN
    ]
    actors = []
    for item in processes + functions:
        actor = _clean_str(item.get("actor"))
        if actor and actor not in actors:
            actors.append(actor)
    purpose = [
        f"1.1 Настоящий Регламент устанавливает порядок выполнения процесса «{heading}».",
    ]
    if actors:
        purpose.append(
            "1.2 Исполнители процесса: " + ", ".join(actors) + "."
        )
    work_sections: list[dict[str, Any]] = []
    if processes:
        for index, process in enumerate(processes, start=1):
            work_sections.append(_document_section_from_process(process, index=index))
    elif functions:
        for index, func in enumerate(functions, start=1):
            work_sections.append(_document_section_from_function(func, index=index))
    resources: list[str] = []
    for process in processes:
        facts = process.get("knownFacts") if isinstance(process.get("knownFacts"), dict) else {}
        location = _clean_str(facts.get("workLocation"))
        if location:
            resources.append(location)
        for obj in _clean_list(facts.get("objects") or []):
            resources.append(obj)
    for func in functions:
        tool = _clean_str(func.get("tool"))
        if tool:
            resources.append(tool)
    seen: set[str] = set()
    unique_resources: list[str] = []
    for item in resources:
        if item in seen:
            continue
        seen.add(item)
        unique_resources.append(item)
    sections = [
        {"number": "1", "title": sto_sections[0], "paragraphs": purpose, "items": []},
        {"number": "2", "title": sto_sections[1], "paragraphs": [], "items": ["СТО-34-003 «Управление документированной информацией»"]},
        {"number": "3", "title": sto_sections[2], "paragraphs": ["В настоящем Регламенте применяются термины, необходимые для исполнения процесса."], "items": []},
        {"number": "4", "title": sto_sections[3], "paragraphs": [], "items": []},
        {
            "number": "5",
            "title": sto_sections[4],
            "paragraphs": [f"Ответственность за исполнение несут: {', '.join(actors)}."] if actors else [],
            "items": [],
        },
        {"number": "6", "title": sto_sections[5], "paragraphs": [], "items": [], "sections": work_sections},
        {"number": "7", "title": sto_sections[6], "paragraphs": [], "items": unique_resources},
        {"number": "8", "title": sto_sections[7], "paragraphs": [], "items": []},
        {"number": "9", "title": sto_sections[8], "paragraphs": ["Приложений нет"], "items": []},
    ]
    return {"title": heading, "sections": sections}


def _document_section_from_function(func: dict[str, Any], *, index: int) -> dict[str, Any]:
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
    return {
        "number": f"6.{index}",
        "title": heading,
        "paragraphs": paragraphs,
        "items": items,
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
