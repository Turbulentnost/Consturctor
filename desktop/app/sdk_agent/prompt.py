from __future__ import annotations

import re

from app.api_client import WorkflowRecord
from app.sdk_agent.tool_adapter import sdk_tool_specs


def format_tool_catalog(limit: int = 80) -> str:
    lines: list[str] = []
    for item in sdk_tool_specs()[: max(limit, 0)]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        description = str(item.get("description") or "").strip().splitlines()[0]
        lines.append(f"- {name}: {description}" if description else f"- {name}")
    return "\n".join(lines) if lines else "- (catalog empty)"


def inferred_design_answers(workflow: WorkflowRecord) -> list[tuple[str, str]]:
    blob = "\n".join(
        part
        for part in (
            workflow.notes or "",
            workflow.document_text or "",
            workflow.title or "",
        )
        if str(part or "").strip()
    )
    low = blob.casefold().replace("ё", "е")
    answers: list[tuple[str, str]] = []
    if re.search(r"событийн.{0,30}триггер|триггер.{0,30}событи|событие вместо расписания", low):
        answers.append((
            "Когда запускать агента?",
            "событийный триггер из материалов",
        ))
    when_labeled = _first_labeled_value(
        blob,
        ("когда запускать", "расписание агента", "запуск агента", "триггер агента"),
    )
    if when_labeled:
        answers.append(("Когда запускать агента?", when_labeled))
    recipient = _first_labeled_value(blob, ("получатель", "адресат", "кому отправлять"))
    if recipient:
        answers.append(("Кому отправлять результат?", recipient))
    success = _first_labeled_value(blob, ("критерий успеха", "критерии успеха", "успешно если"))
    if success:
        answers.append(("По каким критериям считать результат успешным?", success))
    return answers


def _first_labeled_value(text: str, labels: tuple[str, ...]) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip(" -\t")
        if not stripped:
            continue
        folded = stripped.casefold().replace("ё", "е")
        for label in labels:
            if not folded.startswith(label):
                continue
            value = re.split(r"[:\-–]", stripped, maxsplit=1)
            if len(value) == 2 and value[1].strip():
                return value[1].strip()
    return ""


def _inferred_design_facts(workflow: WorkflowRecord) -> list[str]:
    answers = inferred_design_answers(workflow)
    facts: list[str] = []
    when_answer = next((answer for question, answer in answers if "Когда" in question), "")
    if "событийный" in when_answer:
        facts.append(
            "when_to_run: событийный триггер из материалов; не спрашивай расписание или частоту запуска."
        )
    elif "ручной" in when_answer:
        facts.append("when_to_run: ручной запуск из материалов; не спрашивай расписание.")
    elif when_answer:
        facts.append("when_to_run: периодический запуск указан в материалах; не спрашивай расписание.")
    for question, answer in answers:
        if "Кому" in question:
            facts.append(f"recipient: {answer}; не спрашивай получателя.")
        elif "критериям" in question:
            facts.append(f"success_criteria: {answer}; не спрашивай критерий успеха.")
    if facts:
        facts.append("Не добавляй эти параметры в required_clarifications.")
    return facts


def build_design_sdk_prompt(workflow: WorkflowRecord, design_prompt: str) -> str:
    prompt = (design_prompt or "").strip()
    catalog = format_tool_catalog()
    inferred = _inferred_design_facts(workflow)
    header = [
        "Ты локальный Cursor SDK агент Constructor.",
        "Инструменты Constructor уже подключены как customTools (внутренний MCP custom-user-tools).",
        "Это не проектные MCP-серверы Cursor и не mcp.json репозитория.",
        "Не ищи MCP в проекте и не пиши, что MCP не найден: список инструментов ниже.",
        "Live-данные бери через Constructor tools; файлы, код и анализ делай tools Cursor SDK.",
        "Если Constructor tool вернул externalized=true и result_file: продолжай по summary и sample.",
        "Не вызывай тот же tool повторно. Cursor Read по result_file - только если нужна одна запись.",
        "Сначала собери инструкцию будущего агента, а не отчёт по материалам.",
        "Перед JSON проверь: сможет ли агент на следующем запуске отработать,",
        "не додумывая бизнес-правило, которого нет в тексте.",
        "Если для шага пришлось бы угадать фильтр, охват, повод запуска,",
        "адресата или правило решения — спроси этот пробел через askQuestion.",
        "Не ограничивайся заранее заданным списком тем и не спрашивай тему",
        "только потому, что она типичная. Спрашивай пробел из этих материалов.",
        "Не спрашивай то, что материалы уже прямо говорят.",
        "Не подставляй очевидный дефолт вместо вопроса.",
        "Игнорируй требование сразу вернуть только JSON, если такой пробел ещё открыт.",
        "askQuestion уже есть в списке Constructor tools: не ищи его в MCP",
        "и не описывай JSON-схему. В одном вызове ровно один пробел и один вопрос.",
        "Не переформулируй вопрос, на который ответ уже получен.",
        "После ответа запиши значение в JSON (answers и подходящие поля черновика).",
        "В required_clarifications оставляй только то, на что ответа ещё нет.",
        "JSON-черновик пиши после закрытых пробелов, не вместо вопросов.",
        "Не заканчивай проектирование текстом вроде 'уточнения не нужны' без JSON.",
        "После JSON остановись. Не начинай второй круг thinking и не повторяй план.",
        "Показывай ход проектирования коротко, по делу, шаг за шагом.",
        "Финальный ответ должен содержать пригодный JSON-черновик по схеме ниже.",
        "",
        "Доступные инструменты Constructor:",
        catalog,
    ]
    if inferred:
        header.extend(["", "Уже выведено из материалов:"])
        header.extend(f"- {item}" for item in inferred)
    if prompt:
        return "\n".join([*header, "", prompt])
    return build_sdk_prompt(
        workflow,
        "Спроектируй инструкцию агента: сформируй план достижения цели и верни JSON-черновик шагов.",
    )


def build_sdk_prompt(workflow: WorkflowRecord, user_message: str) -> str:
    plan = workflow.plan
    parts: list[str] = [
        "Ты локальный ИИ-агент Constructor.",
        "Работай только по паспорту агента и используй доступные tools, когда нужны живые данные.",
        "Инструменты Constructor переданы как customTools (custom-user-tools), не как проектный MCP.",
        "Не пиши, что MCP не найден, если нужный инструмент есть в списке ниже.",
        "Не пиши JSON вызова инструмента в чат. Вызывай настоящий tool.",
        "Live-данные бери через Constructor tools; файлы, код и анализ делай tools Cursor SDK.",
        "Если Constructor tool вернул externalized=true и result_file: продолжай по summary и sample.",
        "Не вызывай тот же tool повторно. Cursor Read по result_file - только если нужна одна запись.",
        "После 1-3 живых фактов пиши WORK_RESULT. Не снимай весь портфель карточками.",
        "",
        "Доступные инструменты Constructor:",
        format_tool_catalog(),
        "",
        f"Название агента: {workflow.title or 'ИИ-агент'}",
    ]
    if plan is not None:
        if plan.goal:
            parts.extend(["", f"Цель: {plan.goal}"])
        if plan.constraints:
            parts.extend(["", "Ограничения:"])
            parts.extend(f"- {item}" for item in plan.constraints if str(item).strip())
        if plan.out_of_scope:
            parts.extend(["", "Запрещено / вне рамок:"])
            parts.extend(f"- {item}" for item in plan.out_of_scope if str(item).strip())
        steps = plan.steps or []
        if steps:
            parts.extend(["", "Шаги работы:"])
            for step in steps:
                text = step.action or step.title
                if text:
                    parts.append(f"- {step.id or step.title}: {text}")
                if step.done_when:
                    parts.append(f"  Готово когда: {step.done_when}")
        if plan.test_criteria:
            parts.extend(["", "Критерии результата:"])
            parts.extend(f"- {item}" for item in plan.test_criteria if str(item).strip())
        if plan.raw_text:
            parts.extend(["", "Исходный паспорт/инструкция:", plan.raw_text[:8000]])
    if workflow.last_result:
        parts.extend(["", "Пример прошлого успешного прогона:", workflow.last_result[:6000]])
    if workflow.document_text:
        parts.extend(["", "Фрагмент исходного регламента:", workflow.document_text[:6000]])
    parts.extend(
        [
            "",
            "Задача пользователя:",
            user_message.strip(),
            "",
            "В финале дай понятный результат: что проверил, какие факты нашёл, что сделал, какие файлы/уведомления создал.",
        ]
    )
    return "\n".join(parts)


def build_demo_sdk_prompt(workflow: WorkflowRecord) -> str:
    task = (
        "Продолжи работу этого агента и выполни пробный прогон на реальных доступных tools. "
        "Сформируй устойчивую инструкцию для будущих повторных запусков. "
        "Не обходи все 200+ проектов: индекс, затем до 3 карточек с риском, затем отчёт. "
        "В ответе обязательно укажи WORK_RESULT, какие tools использованы, TESTS: PASS или TESTS: FAIL, "
        "и краткую инструкцию playbook для следующего запуска."
    )
    return build_sdk_prompt(workflow, task)
