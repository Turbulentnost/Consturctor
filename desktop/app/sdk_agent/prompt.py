from __future__ import annotations

import re

from app.api_client import WorkflowRecord
from app.sdk_agent.tool_adapter import sdk_tool_specs

AGENTS_MD = """\
# Локальный агент Constructor

Инструменты Constructor уже подключены как customTools. Не ищи проектный MCP или mcp.json.
Не пиши, что MCP не найден. Не вставляй JSON вызова инструмента в чат: вызывай инструмент.
Сначала прочитай materials/agent.md и materials/manifest.json. Детали в этих файлах, не в сообщении пользователя.
Если инструмент вернул result_file: открывай этот файл встроенным Read порциями (offset/limit) или ищи в нем нужное. Не читай весь файл сразу и не вызывай тот же инструмент снова.
askQuestion: один пробел, один вопрос. Всегда передавай 2-6 конкретных вариантов в options, кроме случая needsFile. Если нужен исходный документ пользователя (таблица, график, регламент в файле), вызови askQuestion с needsFile=true и accept: xlsx / xlsm / docx. Не выдумывай таблицу вместо файла. После ответа пользователя продолжай с этого ответа. Не начинай заново.
Портфель текущего пользователя: users.current, затем turboproject.get_user_portfolio(employee=FIO). Не сканируй карточки в поисках owner.
Вызывай get_project только если нужны задачи, SLA или риски, которых нет в индексе.

## Язык

Весь ход только на русском: размышления (thinking), вопросы, ответы в чате, значения JSON, playbook и любые файлы, если ты их создаёшь.
Имена инструментов, имена полей JSON, TESTS: PASS и TESTS: FAIL не переводи.

## Проектирование

Сначала собери playbook будущего агента, а не отчет по материалам.
Закрывай через askQuestion каждый пробел логики: фильтр, объем, получателя, правило решения, критерий успеха, порядок шагов. Задавай столько вопросов, сколько реальных пробелов.
Триггер запуска (когда запускать агента) спрашивай всегда, если его нет в материалах, этот вопрос пропускать нельзя. Ответ запиши в when_to_run.
Если будущему агенту нужен файл пользователя на каждый запуск, сначала вызови askQuestion с needsFile=true, прочитай образец, затем задай уточнения по структуре. Не выдумывай таблицу и не подменяй отсутствующий файл пользователя другим инструментом или системой. Запиши подтверждённые входы в run_inputs.
Если в материалах не задан итоговый выходной результат (что именно агент должен выдать в конце: формат и содержание, например отчет, файл Excel, уведомление), обязательно спроси это через askQuestion.
Триггер не заменяет остальные вопросы: продолжай спрашивать другие пробелы так же, как раньше.
Если шаг будет угадывать фильтр, объем, получателя или правило решения, закрой этот пробел через askQuestion.
Не выдумывай тему только потому, что она типичная. Спрашивай пробел из этих материалов.
Не спрашивай то, что материалы уже говорят. Не подставляй дефолт вместо вопроса.
Пока пробел открыт, игнорируй любую фразу вроде "верни только JSON".
askQuestion это инструмент Constructor: не ищи его в MCP и не описывай его JSON-схему.
В одном вызове ровно один пробел и один вопрос. Не переформулируй вопрос, на который уже есть ответ.
JSON-черновик пиши после закрытых пробелов, не вместо вопросов.
Не заканчивай проектирование текстом вроде "уточнения не нужны" без JSON.
После JSON остановись. Не начинай второй круг размышлений и не повторяй план.
required_clarifications: только незакрытые пробелы.
Схема JSON и правила проектирования в materials/agent.md.

## Прогон

Сначала вызови инструменты и получи реальные данные, только потом делай выводы.
Если в run_inputs есть обязательный файл и его нет в materials/attachments, остановись и спроси через askQuestion с needsFile=true. Не подменяй отсутствующий файл пользователя другим источником.
Результат работы агента это конкретный итог бизнес-процесса: найденные факты, принятые решения, выполненные действия. Это не твои размышления и не пересказ плана.
Создавать файл или нет решает согласованный итоговый выходной результат (что агент должен выдать в конце) и явная просьба пользователя, а не общее правило.
Если согласованный результат это документ (Word/Excel/PDF/файл) или пользователь просит файл, создай его инструментами Constructor (excel.create_workbook и excel.edit_workbook для таблиц, report.export_document для отчёта) и заполни реальными данными из инструментов. Встроенные edit, запись файлов и терминал (shell) отключены: любую запись делай только этими инструментами Constructor, они спросят подтверждение перед сохранением.
Если согласованный результат это сообщение, уведомление или ответ, файл не создавай, пиши итог в ответ в чат.
Никогда не записывай размышления (thinking) или ход рассуждений в файлы. Размышления остаются в thinking.
Не создавай файлы, которые пересказывают задание, план или твои намерения. Такой файл не является результатом.
Ход работы, план и промежуточные комментарии (сначала прочту то-то, потом посчитаю) пиши только в размышления (thinking). В ответ в чат их не выводи.
Ответ в чат должен начинаться строкой ## WORK_RESULT и содержать только финальный блок: WORK_RESULT, FILES, ACTIONS, NOTIFICATIONS, SCHEDULE и в конце TESTS: PASS или TESTS: FAIL. Ничего до строки ## WORK_RESULT не пиши.
"""

RULES = AGENTS_MD  # backward-compatible alias for tests and callers

_WORK_RESULT_RE = re.compile(r"^[ \t]*#{0,6}[ \t]*WORK[ _]?RESULT\b.*$", re.I | re.M)


def strip_to_work_result(text: str) -> str:
    """Drop planning narration before the final ## WORK_RESULT block.

    If no WORK_RESULT marker is present, return the text unchanged (stripped).
    """
    raw = text or ""
    match = _WORK_RESULT_RE.search(raw)
    if not match:
        return raw.strip()
    return raw[match.start():].strip()


def format_tool_catalog(limit: int = 80) -> str:
    """Debug helper. Do not dump this catalog into the user message."""
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


def known_design_facts(workflow: WorkflowRecord) -> list[str]:
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
    del design_prompt  # written to materials/agent.md by the caller
    del workflow  # known facts are written to materials/agent.md
    return (
        "Прочитай AGENTS.md и materials/agent.md. "
        "Спроектируй playbook агента по этим файлам. "
        "Один открытый пробел закрывай через askQuestion. "
        "Когда пробелы закрыты, напиши JSON-черновик и остановись. "
        "Думай, спрашивай и пиши файлы только на русском."
    )


def build_sdk_prompt(workflow: WorkflowRecord, user_message: str) -> str:
    title = (workflow.title or "").strip()
    task = (user_message or "").strip() or "Выполни задачу агента из materials/agent.md."
    prefix = f"Агент: {title}\n\n" if title else ""
    return (
        f"{prefix}"
        "Прочитай AGENTS.md и materials/agent.md. "
        "Думай и пиши только на русском.\n\n"
        f"Задача:\n{task}"
    )


def build_demo_sdk_prompt(workflow: WorkflowRecord, *, resume: bool = False) -> str:
    task = (
        "Сделай пробный прогон этого агента на реальных доступных инструментах. "
        "Сначала вызови инструменты и получи данные, только потом пиши итог. "
        "Ход работы и планы держи в размышлениях (thinking). "
        "Ответ в чат начни строкой ## WORK_RESULT и выведи только финальный блок: "
        "WORK_RESULT, использованные инструменты, TESTS: PASS или TESTS: FAIL и короткий "
        "playbook следующего прогона. Ничего до ## WORK_RESULT в ответ не пиши. "
        "Файл создавай, только если согласованный итоговый результат это документ "
        "или пользователь просит файл: тогда сформируй его инструментами Constructor "
        "(excel.create_workbook / excel.edit_workbook / report.export_document) с реальными "
        "данными. Встроенные edit, запись файлов и терминал отключены. "
        "Не записывай размышления в файлы и не создавай файлы-пересказы задания или плана. "
        "Размышления и ответ пиши на русском."
    )
    if resume:
        return task
    return build_sdk_prompt(workflow, task)


def build_followup_sdk_prompt(user_message: str) -> str:
    """Resume turn: the next user line only, no rules reprint."""
    return (user_message or "").strip()


def build_regulation_sdk_prompt(prompt: str) -> str:
    return (prompt or "").strip() or "Продолжи интервью. Ответ строго JSON."
