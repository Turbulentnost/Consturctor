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
askQuestion: один пробел, один вопрос. Всегда передавай 2-6 конкретных вариантов в options, кроме случая needsFile. Если нужен исходный документ пользователя (таблица, график, регламент, скан, фото, PDF), вызови askQuestion с needsFile=true. Можно Word, Excel, PDF, изображения и другие файлы; сканы и фото читаются через OCR. Не выдумывай таблицу вместо файла. После ответа пользователя продолжай с этого ответа. Не начинай заново.
Портфель текущего пользователя: users.current, затем turboproject.get_user_portfolio(employee=FIO). Не сканируй карточки в поисках owner.
Вызывай get_project только если нужны задачи, SLA или риски, которых нет в индексе.

## Язык

Весь ход только на русском: размышления (thinking), вопросы, ответы в чате, значения JSON, playbook и любые файлы, если ты их создаёшь.
Имена инструментов, имена полей JSON, TESTS: PASS и TESTS: FAIL не переводи.

## Проектирование

Сначала собери playbook будущего агента, а не отчет по материалам.
Закрывай через askQuestion каждый пробел логики: фильтр, объем, получателя, правило решения, критерий успеха, порядок шагов. Задавай столько вопросов, сколько реальных пробелов.
Если материалы уже говорят, когда идёт процесс (час, утро, срок, событие), запиши это в when_to_run и не спрашивай, когда запускать агента: он стартует так же, как написано. Спрашивай триггер только если в тексте нет ни времени, ни частоты, ни события запуска.
Если будущему агенту нужен файл пользователя на каждый запуск, сначала вызови askQuestion с needsFile=true, прочитай образец, затем задай уточнения по структуре. Не выдумывай таблицу и не подменяй отсутствующий файл пользователя другим инструментом или системой. Запиши подтверждённые входы в run_inputs.
Если материалы уже называют результат процесса (комплект, протокол, список решений, запись в системе), это и есть выход агента. Не спрашивай «в каком виде» и не добавляй акт, Word, Excel или уведомление, если этого нет в материалах. Спрашивай выход только если нет ни содержания, ни получателя результата. Не спрашивай входы, сроки и систему, если они уже перечислены.
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

## Запуск

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
Строку TESTS: PASS или TESTS: FAIL пиши ровно один раз, в самом конце блока WORK_RESULT. Никогда не упоминай TESTS: PASS в размышлениях или в прозе до блока: это сигнал завершения, преждевременное упоминание обрывает запуск.
Даже если ты уже что-то рассуждал в чате, всё равно заверши ответ полноценным блоком ## WORK_RESULT. Все инструменты (в т.ч. визуализацию, например calendar.show_meetings) вызывай до блока, а не описывай словами вместо вызова.
Шаблон ответа в чат (замени на реальные данные, пустые разделы пропусти):

## WORK_RESULT
<кратко: что сделано и главный итог процесса>

## FILES
- <имя файла>: <что внутри>

## ACTIONS
- <какое действие выполнено>

## NOTIFICATIONS
- <кому и что отправлено>

## SCHEDULE
- <если менялось расписание>

TESTS: PASS
"""

RULES = AGENTS_MD  # backward-compatible alias for tests and callers

_WORK_RESULT_RE = re.compile(r"#{0,6}[ \t]*WORK[ _]?RESULT\b", re.I)
_FILES_SECTION_RE = re.compile(r"(?:^|[\n\r])[ \t]*FILES\b", re.I)
_ACTIONS_SECTION_RE = re.compile(r"(?:^|[\n\r])[ \t]*ACTIONS\b", re.I)
_TESTS_PASS_RE = re.compile(r"TESTS:\s*PASS", re.I)
_TESTS_FAIL_RE = re.compile(r"TESTS:\s*FAIL", re.I)


def text_has_finished_work_result(text: str) -> bool:
    """True when the run produced a closable result block, not just the words TESTS: PASS."""
    raw = text or ""
    if _TESTS_FAIL_RE.search(raw) or not _TESTS_PASS_RE.search(raw):
        return False
    if _WORK_RESULT_RE.search(raw):
        return True
    return bool(_FILES_SECTION_RE.search(raw) and _ACTIONS_SECTION_RE.search(raw))


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
        ("когда запускать", "расписание агента", "запуск агента", "триггер агента", "триггер", "условия"),
    )
    if when_labeled:
        answers.append(("Когда запускать агента?", when_labeled))
    else:
        extracted = _schedule_from_blob(blob)
        if extracted:
            answers.append(("Когда запускать агента?", extracted))
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


def _schedule_from_blob(text: str) -> str:
    """Process cadence from materials is the agent trigger, not a gap."""
    for line in (text or "").splitlines():
        stripped = line.strip(" -\t")
        if not stripped:
            continue
        folded = stripped.casefold().replace("ё", "е")
        if re.search(r"каждый час|раз в час|ежечасн|каждые\s+\d+", folded):
            return stripped
        if re.search(r"(утром|вечером|к)\s+\d{1,2}[:.]\d{2}", folded):
            return stripped
        if re.search(r"(ежедневн|каждый день|раз в день).{0,20}\d{1,2}[:.]\d{2}", folded):
            return stripped
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


def _is_meeting_run_agent(workflow: WorkflowRecord) -> bool:
    local = workflow.local_run if isinstance(workflow.local_run, dict) else {}
    runtime = local.get("runtime") if isinstance(local.get("runtime"), dict) else {}
    kind = str(runtime.get("kind") or "").casefold()
    if kind in {"revision_commission", "board_meeting", "sd_meeting"}:
        return True
    blob = "\n".join(
        str(part or "")
        for part in (
            workflow.title,
            workflow.notes,
            (local.get("playbook") or {}).get("instructions")
            if isinstance(local.get("playbook"), dict)
            else "",
        )
    ).casefold()
    return any(
        hint in blob
        for hint in (
            "ревизионной комиссии",
            "ревизионная комиссия",
            "совета директоров",
            "пл-01-001",
            "пл-34-242",
        )
    )


def build_sdk_prompt(workflow: WorkflowRecord, user_message: str) -> str:
    title = (workflow.title or "").strip()
    task = (user_message or "").strip() or "Выполни задачу агента из materials/agent.md."
    prefix = f"Агент: {title}\n\n" if title else ""
    if _is_meeting_run_agent(workflow):
        read_hint = (
            "Прочитай только materials/agent.md (один Read). "
            "Не делай Glob по materials/ и не читай manifest подряд — регламент уже в agent.md. "
            "Сразу после agent.md вызывай инструменты Constructor (Outlook, 1С, Excel, отчёт). "
            "Заверши ## WORK_RESULT и TESTS: PASS."
        )
    else:
        read_hint = "Прочитай AGENTS.md и materials/agent.md."
    return (
        f"{prefix}{read_hint} "
        "Думай и пиши только на русском.\n\n"
        f"Задача:\n{task}"
    )


def build_demo_sdk_prompt(workflow: WorkflowRecord, *, resume: bool = False) -> str:
    task = (
        "Сделай пробный запуск этого агента на реальных доступных инструментах. "
        "Сначала вызови инструменты и получи данные, только потом пиши итог. "
        "Ход работы и планы держи в размышлениях (thinking). "
        "Ответ в чат начни строкой ## WORK_RESULT и выведи только финальный блок: "
        "WORK_RESULT, использованные инструменты, TESTS: PASS или TESTS: FAIL и короткий "
        "playbook следующего запуска. Ничего до ## WORK_RESULT в ответ не пиши. "
        "Файл создавай, только если согласованный итоговый результат это документ "
        "или пользователь просит файл: тогда сформируй его инструментами Constructor "
        "(excel.create_workbook / excel.edit_workbook / report.export_document) с реальными "
        "данными. Встроенные edit, запись файлов и терминал отключены. "
        "Не записывай размышления в файлы и не создавай файлы-пересказы задания или плана. "
        "Если нужно показать план встреч или расписание, вызови инструмент визуализации "
        "(calendar.show_meetings) до блока WORK_RESULT, а не описывай его словами. "
        "TESTS: PASS пиши только один раз в конце блока WORK_RESULT, не раньше. "
        "Если агент меняет любую сущность 1С, конструктор сам делает пробу "
        "CONSTRUCTOR_PROBE (создать объект, проверить изменение, удалить). "
        "Не создавай ещё тестовые карточки и не пиши в боевые без подтверждения. "
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
