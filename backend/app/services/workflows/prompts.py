from __future__ import annotations

import json
import re
from typing import Any

from app.services.workflows.plan_models import OpenQuestion, PlanStep, WorkflowPlan

PLAN_SCHEMA_HINT = """
Верни ТОЛЬКО один JSON-объект (можно в блоке ```json), без лишнего текста вокруг.
Схема:
{
  "title": "string",
  "goal": "string",
  "constraints": ["string"],
  "out_of_scope": ["string"],
  "steps": [
    {
      "id": "s1",
      "title": "string",
      "action": "string",
      "done_when": "string",
      "depends_on": ["s0"]
    }
  ],
  "test_criteria": ["string"],
  "open_questions": [
    {
      "id": "q1",
      "question": "string",
      "why": "string",
      "options": ["string"],
      "answer": "string"
    }
  ],
  "answered_questions": [
    {
      "id": "q1",
      "question": "string",
      "why": "string",
      "answer": "string",
      "options": ["string"]
    }
  ],
  "runtime": {
    "kind": "site_search_excel | outlook_calendar | browser_task | onec | \"\"",
    "site_url": "https://...",
    "keywords": ["фраза1", "фраза2"],
    "keyword_text": "исходный перечень как у пользователя",
    "export": {
      "format": "xlsx",
      "destination": "desktop",
      "columns": ["название", "цена", "дата", "ссылка", "ключевые слова"]
    }
  }
}
Правила:
- steps — конкретные шаги реализации, по порядку зависимостей.
- Пользователь — не разработчик. Спрашивай ТОЛЬКО то, что может решить только человек:
  кому слать, как сообщить результат, как часто запускать, что считать успехом.
  Максимум 3 открытых вопроса. Лучше меньше.
- Вопрос и options — простыми словами, без внутренних имён (q14, resheniya, entity),
  без инструментов и протоколов. Плохо: «вызвать notify / onec.odata / turboproject».
  Хорошо: «Прислать уведомление», «Сформировать отчёт», «Записать в журнал».
- Куда смотреть и какой tool вызывать — решает агент сам. Это не вопрос пользователю.
- ЗАПРЕЩЕНО спрашивать: URL/логин/пароль, OData/COM/IMAP/fixtures/live,
  точные имена полей/справочников, GUID, «значение N» для формулы,
  если пользователь уже сказал «не знаю / выясни сам / определи сам».
- Ответ «не знаю», «выясни сам», «посмотри сам», «как они называются — найди»
  = поручение агенту. Закрой тему, не задавай follow-up по тем же деталям.
- Не повторяй уже заданную тему даже с другим id. Не дроби одну тему на микровопросы.
- open_questions — только критичные человеческие решения; иначе [].
  Пока список не пуст: черновик title/goal, без подробных steps.
- answered_questions — ВСЕ ответы (id/question/answer). Не удаляй и не забывай.
- options — 2–4 понятных действия/выбора. Не «Да/Нет», если нужен смысл.
- runtime — машиночитаемые правила запуска ИМЕННО ЭТОГО агента из ответов пользователя.
  Не подставляй чужие словари и не копируй примеры из схемы, если пользователь их не давал.
- kind выбирай по домену агента И ответам:
  - site_search_excel — поиск на сайте/ЭТП по ключам + Excel;
  - outlook_calendar — совещания / календарь Outlook / планирование встреч
    (если пользователь сказал COM/Outlook — отрази это в constraints и steps, не подменяй на web_search/site_browser);
  - onec — если пользователь указал 1С / OData / COM к 1С;
  - browser_task — работа в конкретном веб-приложении по URL;
  - иначе runtime={} или опусти поле (не ставь site_search_excel «по умолчанию»).
- keywords — только для site_search_excel (разбей перечисления пользователя на элементы).
- Не пиши код реализации в этом ответе.
""".strip()


_PLACEHOLDER_TITLES = {
    "notes",
    "notes.txt",
    "без названия",
    "материалы",
    "files",
    "агент",
    "ии-агент",
}

_RESULT_HINT = (
    "Сначала пойми, зачем этот агент нужен и чем заканчивается его работа.\n"
    "В конце прогона всегда верни предметный результат — не «Готово» и не JSON инструмента.\n"
    "Формат (текст обязателен):\n"
    "RESULT:\n"
    "<3–12 предложений: что проверил, что нашёл, что сделал, кому сообщил>\n"
    "FILES:\n"
    "- путь или нет\n"
    "ACTIONS:\n"
    "- действие или нет\n"
    "NOTIFICATIONS:\n"
    "- кому и что или нет\n"
    "SCHEDULE:\n"
    "- каждые 15 мин / ежедневно в 12:00 / при событии: … / только вручную\n"
)


def is_placeholder_title(value: str) -> bool:
    return (value or "").strip().casefold() in _PLACEHOLDER_TITLES


def title_from_materials(
    *,
    notes: str = "",
    document_text: str = "",
    document_name: str = "",
    fallback: str = "ИИ-агент",
) -> str:
    blobs = [notes or "", document_text or ""]
    for blob in blobs:
        for line in blob.splitlines():
            stripped = line.strip().lstrip("#").strip()
            match = re.search(r"Паспорт ИИ-агента:\s*(.+)$", stripped, re.IGNORECASE)
            if match:
                name = _clean_agent_title(match.group(1))
                if name and not is_placeholder_title(name):
                    return name[:180]
            match = re.match(r"ИИ-агент:\s*(.+)$", stripped, re.IGNORECASE)
            if match:
                name = _clean_agent_title(match.group(1))
                if name and not is_placeholder_title(name) and name.casefold() != "—":
                    return name[:180]
    doc = (document_name or "").strip()
    if doc and not is_placeholder_title(doc):
        return doc[:180]
    return fallback


def _clean_agent_title(value: str) -> str:
    name = (value or "").strip().strip("«»\"'")
    name = re.sub(r"^ИИ-агент:\s*", "", name, flags=re.IGNORECASE).strip()
    return name


def parse_work_result(text: str) -> dict[str, Any]:
    raw = text or ""
    cleaned = re.sub(r"```\s*(?:constructor_tool|tool)\b.*?```", "", raw, flags=re.S | re.I)
    cleaned = re.sub(r"```\s*(?:constructor_tool|tool)\b", "", cleaned, flags=re.I)
    files = _bullet_section(cleaned, "FILES")
    actions = _bullet_section(cleaned, "ACTIONS")
    notifications = _bullet_section(cleaned, "NOTIFICATIONS")
    schedule = _bullet_section(cleaned, "SCHEDULE")
    result_text = _named_section(cleaned, "RESULT")
    if not result_text:
        result_text = _named_section(cleaned, "Результат")
    if not result_text:
        result_text = _fallback_result_text(cleaned)
    return {
        "text": (result_text or "").strip()[:4000],
        "files": files,
        "actions": actions,
        "notifications": notifications,
        "schedule": schedule,
    }


def _named_section(text: str, heading: str) -> str:
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:#+\s*)?{re.escape(heading)}\s*:?\s*(.*?)(?=\n\s*(?:FILES|ACTIONS|NOTIFICATIONS|SCHEDULE|CLARIFY)\s*:|\n```|\Z)",
        re.S | re.I,
    )
    match = pattern.search(text or "")
    if not match:
        return ""
    body = match.group(1).strip()
    return body


def _bullet_section(text: str, heading: str) -> list[str]:
    body = _named_section(text, heading)
    if not body:
        return []
    items: list[str] = []
    for line in body.splitlines():
        stripped = line.strip().lstrip("-•*").strip()
        if not stripped or stripped.casefold() in {"нет", "нет.", "—", "-"}:
            continue
        items.append(stripped[:240])
    return items[:12]


def _fallback_result_text(text: str) -> str:
    parts: list[str] = []
    skip = False
    for line in (text or "").splitlines():
        stripped = line.strip()
        low = stripped.casefold()
        if stripped.startswith("```"):
            skip = not skip
            continue
        if skip:
            continue
        if low.startswith(("clarify", "question:", "options:", "why:", "thinking")):
            continue
        if "constructor_tool" in low:
            continue
        if any(token in stripped for token in ('"name":', '"arguments":', "$filter", "$top")):
            continue
        if stripped.startswith("{") or stripped.startswith("}"):
            continue
        if stripped:
            parts.append(stripped)
    blob = "\n".join(parts).strip()
    if len(blob) > 2000:
        blob = blob[:2000].rsplit("\n", 1)[0].strip()
    return blob


_DEMO_CLARIFY_HINT = (
    "Подсмотреть данные через ```constructor_tool можно (имена, чтобы предложить варианты). "
    "Угадывать решения, которых нет в ТЗ и которые меняют расчёт, нельзя.\n"
    "Если в материалах не сказано явно — спроси и остановись, не ставь default:\n"
    "- кого/что брать в расчёт (объекты, люди, участие, подчинённые) — не бери «все»;\n"
    "- когда и как часто это делать;\n"
    "- в каком виде и кому отдавать результат;\n"
    "- что считать успехом / просрочкой / «важным», если формулировка двусмысленна.\n"
    "Спрашивай только то, чего нет в ЭТОМ ТЗ. Не выдумывай формулировку вопроса заранее.\n"
    "После CLARIFY не обрабатывай каталог и не вызывай tool на полный разбор в том же ответе:\n"
    "CLARIFY:\n"
    "QUESTION: …\n"
    "OPTIONS:\n"
    "- вариант\n"
    "WHY: в материалах этого решения нет\n"
    "В видимом ответе — только принятые решения и вопросы человеку. "
    "Поиск tool / MCP / URL / OData — не пиши в основной текст.\n"
    "Не спрашивай техническое: поля, справочники, OData, COM, имена tools, URL, логины. "
    "Куда смотреть и какой tool — реши сам по каталогу Constructor.\n"
    "Не пиши PLAN_SCHEMA и open_questions JSON."
)


def _clip_demo_materials(*, document_text: str, notes: str = "") -> str:
    clipped = (document_text or "").strip()
    if len(clipped) > 60_000:
        clipped = clipped[:60_000] + "\n\n[...truncated...]"
    extra = (notes or "").strip()
    if extra and extra not in clipped:
        clipped = (extra + "\n\n" + clipped).strip() if clipped else extra
    return clipped or "(нет текста — опирайся на название и доступные Constructor tools)"


def build_demo_prompt(
    *,
    document_text: str,
    title: str = "",
    notes: str = "",
    document_name: str = "",
) -> str:
    body = _clip_demo_materials(document_text=document_text, notes=notes)
    return (
        "Ты агент Constructor. Материалы ниже — ТЗ. "
        "Делай только то, что в них явно сказано. Не составляй план-JSON.\n"
        f"{_DEMO_CLARIFY_HINT}\n"
        "Когда человек ответил или решение уже есть в ТЗ — "
        "один реальный прогон на живых данных.\n"
        f"{_RESULT_HINT}\n"
        f"Название: {title_from_materials(notes=notes, document_text=document_text, document_name=document_name, fallback=title or 'агент')}\n"
        f"Источник: {document_name or 'материалы'}\n\n"
        "===== BUSINESS PROCESS =====\n"
        f"{body}\n"
        "===== END ====="
    )


def build_demo_continue_prompt(
    *,
    document_text: str,
    title: str = "",
    notes: str = "",
    document_name: str = "",
    plan: WorkflowPlan | None = None,
) -> str:
    body = _clip_demo_materials(document_text=document_text, notes=notes)
    answers = _answered_scope_lines(plan)
    return (
        "Человек ответил на содержательные вопросы. Продолжи пробный прогон.\n"
        "Делай только указанный объём: не бери «все» объекты, если выбрали конкретные.\n"
        f"{_DEMO_CLARIFY_HINT}\n"
        "Если после ответов смысл ясен — вызывай Constructor tools и дай результат.\n"
        "Если человек просил уведомления / прислать / notify — до RESULT обязательно "
        "вызови users.list и notify.send. Текст «я отправил» без notify.send не считается.\n"
        f"{_RESULT_HINT}\n"
        f"Название: {title_from_materials(notes=notes, document_text=document_text, document_name=document_name, fallback=title or 'агент')}\n"
        f"Источник: {document_name or 'материалы'}\n\n"
        "===== ОТВЕТЫ ЧЕЛОВЕКА =====\n"
        f"{answers or '(ответов нет)'}\n"
        "===== КОНЕЦ ОТВЕТОВ =====\n\n"
        "===== BUSINESS PROCESS =====\n"
        f"{body}\n"
        "===== END ====="
    )


def build_playbook_prompt(
    *,
    title: str,
    demo_text: str,
    tools: list[str] | None = None,
    answered_scope: str = "",
) -> str:
    trace = (demo_text or "").strip()
    if len(trace) > 12_000:
        trace = trace[:12_000] + "\n\n[...truncated...]"
    used = ", ".join(tools or []) or "—"
    scope = (answered_scope or "").strip()
    scope_block = (
        f"Объём, который выбрал человек (обязательно внеси в instructions):\n{scope}\n\n"
        if scope
        else ""
    )
    return (
        "По только что выполненному прогону составь инструкцию для СЕБЯ на следующие запуски.\n"
        "Верни ТОЛЬКО один JSON-объект (можно в ```json):\n"
        "{\n"
        '  "name": "короткое человеческое имя агента, не имя файла",\n'
        '  "instructions": "кратко: цель, какой объём, откуда данные, какой результат, какие tools",\n'
        '  "example_run": "сжатый пример успешного прогона: вызовы и итог",\n'
        '  "expected_result": "что отдавать в следующий раз: текст, файлы, уведомления",\n'
        '  "triggers": [\n'
        "    {\n"
        '      "kind": "interval|event|datetime",\n'
        '      "interval_value": 15,\n'
        '      "interval_unit": "minutes|hours|days",\n'
        '      "condition": "короткое событие до 80 символов",\n'
        '      "at": "HH:MM или ISO",\n'
        '      "once": false,\n'
        '      "message": ""\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "Зафиксируй выбранный объём (какие проекты/люди/период). "
        "Не пиши «бери все», если человек этого не сказал.\n"
        "Если человек просил уведомления — в instructions явно: вызови notify.send.\n"
        "name — из паспорта, не notes.txt.\n"
        "triggers — только если человек или ТЗ сказали, когда запускать; иначе [].\n"
        "condition не копируй абзацем из ТЗ.\n"
        "Без кода, без open_questions, без секретов.\n"
        f"Название: {title or 'агент'}\n"
        f"Tools: {used}\n\n"
        f"{scope_block}"
        "===== DEMO TRACE =====\n"
        f"{trace}\n"
        "===== END ====="
    )


def build_published_run_prompt(
    *,
    instructions: str,
    example_run: str,
    user_message: str,
    title: str = "",
    context: str = "",
    source: str = "chat",
) -> str:
    context_block = ""
    if (context or "").strip():
        context_block = (
            "===== КОНТЕКСТ АГЕНТА =====\n"
            f"{context.strip()}\n"
            "===== КОНЕЦ КОНТЕКСТА =====\n\n"
        )
    role_line = (
        "Сейчас ты выполняешь СВОЮ рабочую задачу агента. "
        "Если пользователь напишет в чат — это дополнительная команда, "
        "её нужно сделать и вернуться к основной работе.\n"
        if (source or "") != "chat"
        else (
            "Это команда из чата. Сделай ИМЕННО её. "
            "Не перезапускай типовой сценарий агента (реестр, OData, Excel), "
            "если пользователь этого не просил. "
            "Для копирования файла используй files.copy.\n"
        )
    )
    return (
        "Ты полноценный агент Constructor — такой же, как Cursor в IDE: "
        "сам планируешь шаги, вызываешь несколько tools подряд, читаешь ошибки "
        "и сам себя исправляешь, пока задача не будет сделана.\n"
        f"{role_line}"
        "Инструменты вызывай отдельным блоком ```constructor_tool — это для системы, не для человека.\n"
        "В обычный чат пиши только понятный русский текст: что делаешь и что получилось. "
        "Не пиши JSON, OData, $filter, имена entity, constructor_tool и аргументы tools.\n"
        "Не ищи MCP Constructor, OIDC, BACKEND_URL и не делай curl с Cloud VM — "
        "серверные инструменты вызываются блоком constructor_tool, backend выполнит их сам.\n"
        "Если tool вернул ошибку — не останавливайся и не спрашивай разрешения. "
        "Смени аргументы, выбери другой tool, напиши/запусти Python "
        "(code.write_python / code.run_python) или разбей задачу и повтори.\n"
        "CLARIFY только если без ответа человека физически нельзя продолжить "
        "(нет ФИО, URL или периода). Не спрашивай «можно ли вызвать tool».\n"
        "Следуй инструкции. Пример прогона — образец, не догма: "
        "если задача чуть другая, адаптируй вызовы.\n"
        "Если в инструкции и задаче сейчас не сказано, какие объекты брать "
        "(проекты, люди, период) — спроси человека блоком CLARIFY и остановись. "
        "Не бери весь каталог по умолчанию.\n"
        "Не спрашивай про поля и протоколы. Не составляй план-JSON.\n"
        "Если инструкция или задача требуют уведомить человека — вызови notify.send "
        "(user_id из users.list). Без этого tool уведомление на компьютер не уйдёт.\n"
        f"{_RESULT_HINT}\n"
        f"Агент: {title or 'ИИ-агент'}\n\n"
        f"{context_block}"
        "===== ИНСТРУКЦИЯ =====\n"
        f"{(instructions or '').strip() or 'Выполни задачу по смыслу бизнес-процесса.'}\n"
        "===== КОНЕЦ ИНСТРУКЦИИ =====\n\n"
        "===== ПРИМЕР УСПЕШНОГО ПРОГОНА =====\n"
        f"{(example_run or '').strip() or '—'}\n"
        "===== КОНЕЦ ПРИМЕРА =====\n\n"
        "===== ЗАДАЧА СЕЙЧАС =====\n"
        f"{(user_message or '').strip()}\n"
        "===== КОНЕЦ ЗАДАЧИ ====="
    )


def parse_playbook_from_text(text: str) -> dict[str, Any]:
    data = _extract_json_blob(text) or {}
    instructions = str(data.get("instructions") or "").strip()
    example = str(data.get("example_run") or data.get("example") or "").strip()
    name = _clean_agent_title(str(data.get("name") or data.get("title") or ""))
    expected = str(data.get("expected_result") or data.get("result") or "").strip()
    if not instructions and (text or "").strip():
        instructions = text.strip()[:2000]
    triggers = data.get("triggers") if isinstance(data.get("triggers"), list) else []
    return {
        "instructions": instructions,
        "example_run": example,
        "name": name,
        "expected_result": expected[:800],
        "triggers": [item for item in triggers if isinstance(item, dict)],
    }


_CLARIFY_TECH_HINTS = (
    "odata",
    "constructor_tool",
    "backend_url",
    "invoker",
    "fixtures",
    "guid",
    "onec.",
    "imap.",
    "com-соедин",
    "логин 1с",
    "пароль",
    "имя поля",
    "имена полей",
    "справочник 1с",
)

_SCOPE_HINTS = (
    "проект",
    "период",
    "сотрудник",
    "подчинён",
    "подчинен",
    "отдел",
    "адресат",
    "уведом",
    "кому",
    "какие ",
    "какой ",
    "за какой",
    "кого ",
    "как часто",
    "расписан",
    "в каком виде",
    "формат",
    "запуск",
    "доставк",
    "триггер",
)


def _is_technical_clarify_question(text: str) -> bool:
    folded = (text or "").casefold().replace("ё", "е")
    return any(hint in folded for hint in _CLARIFY_TECH_HINTS)


def _looks_like_scope_question(text: str) -> bool:
    folded = (text or "").casefold().replace("ё", "е")
    if _is_technical_clarify_question(folded):
        return False
    return any(hint in folded for hint in _SCOPE_HINTS) or "?" in (text or "")


def _answered_scope_lines(plan: WorkflowPlan | None) -> str:
    if plan is None:
        return ""
    lines: list[str] = []
    for q in plan.answered_questions:
        ans = (q.answer or "").strip()
        if not ans:
            continue
        ask = (q.question or "").strip() or q.id
        lines.append(f"- {ask} → {ans}")
    return "\n".join(lines)


def parse_clarify_from_text(text: str) -> list[OpenQuestion]:
    """Content questions the demo agent asked. Technical / infra questions are dropped."""
    blob = text or ""
    found = _parse_clarify_block(blob)
    if not found:
        found = _parse_clarify_json(blob)
    if not found:
        found = _parse_clarify_numbered(blob)
    if not found:
        found = _parse_clarify_fallback(blob)
    kept: list[OpenQuestion] = []
    seen: set[str] = set()
    for i, item in enumerate(found, start=1):
        question = (item.question or "").strip()
        if len(question.rstrip("?")) < 6 or _is_technical_clarify_question(question):
            continue
        key = question.casefold()
        if key in seen:
            continue
        seen.add(key)
        qid = (item.id or "").strip() or f"demo-q{i}"
        options = [opt for opt in item.options if opt and not _is_technical_clarify_question(opt)]
        kept.append(
            OpenQuestion(
                id=qid,
                question=question,
                why=(item.why or "").strip() or "В материалах этот объём не задан",
                options=options[:4],
            )
        )
        if len(kept) >= 5:
            break
    return kept


def _parse_clarify_block(text: str) -> list[OpenQuestion]:
    lines = (text or "").splitlines()
    started = False
    items: list[OpenQuestion] = []
    current: OpenQuestion | None = None
    in_options = False

    def flush() -> None:
        nonlocal current
        if current and (current.question or "").strip():
            items.append(current)
        current = None

    for raw in lines:
        ln = _normalize_clarify_line(raw)
        low = ln.casefold()
        if low.startswith("clarify:") or low == "clarify":
            started = True
            in_options = False
            continue
        if not started:
            continue
        if low.startswith("```") or low.startswith("tests:") or low.startswith("===== "):
            break
        if low.startswith("question:") or low.startswith("вопрос:"):
            flush()
            current = OpenQuestion(id="", question=ln.split(":", 1)[1].strip())
            in_options = False
            continue
        if current is None:
            continue
        if low.startswith("options:") or low.startswith("варианты:"):
            rest = ln.split(":", 1)[1].strip()
            in_options = True
            if rest:
                current.options.append(_strip_option(rest))
            continue
        if low.startswith("why:") or low.startswith("зачем:"):
            current.why = ln.split(":", 1)[1].strip()
            in_options = False
            continue
        if in_options:
            if not ln:
                in_options = False
                continue
            current.options.append(_strip_option(ln))
            if len(current.options) >= 4:
                in_options = False
    flush()
    return items


def _parse_clarify_json(text: str) -> list[OpenQuestion]:
    data = _extract_json_blob(text) or {}
    raw = data.get("clarify") or data.get("open_questions")
    if not isinstance(raw, list):
        return []
    items: list[OpenQuestion] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or entry.get("text") or "").strip()
        if not question:
            continue
        options = entry.get("options") or []
        if not isinstance(options, list):
            options = []
        items.append(
            OpenQuestion(
                id=str(entry.get("id") or ""),
                question=question,
                why=str(entry.get("why") or ""),
                options=[str(x).strip() for x in options if str(x).strip()],
            )
        )
    return items


def _parse_clarify_fallback(text: str) -> list[OpenQuestion]:
    blob = (text or "").strip()
    if not blob or len(blob) > 1200:
        return []
    low = blob.casefold()
    if any(hint in low for hint in ("tests: pass", "tests:pass", "прогон готов")):
        return []
    items: list[OpenQuestion] = []
    for raw in blob.splitlines():
        cleaned = raw.strip()
        cleaned = cleaned.lstrip("-•*").strip()
        cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned).strip()
        if "?" not in cleaned or not cleaned.endswith("?"):
            continue
        if len(cleaned) < 12 or not _looks_like_scope_question(cleaned):
            continue
        items.append(OpenQuestion(id="", question=cleaned))
        if len(items) >= 5:
            break
    return items


def _normalize_clarify_line(text: str) -> str:
    """Cursor often wraps CLARIFY headers in markdown: **QUESTION:**."""
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^#{1,6}\s*", "", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").strip()
    cleaned = re.sub(r"^[`*_]+|[`*_]+$", "", cleaned).strip()
    return cleaned


def _parse_clarify_numbered(text: str) -> list[OpenQuestion]:
    """Prose like '(1) проекты: все / мои / один' after a failed structured block."""
    blob = text or ""
    if "clarify" not in blob.casefold() and "вопрос" not in blob.casefold():
        return []
    items: list[OpenQuestion] = []
    for match in re.finditer(
        r"(?:^|\n)\s*(?:\(?\d+\)?[.)]|[-*•])\s+(.+)",
        blob,
    ):
        body = _normalize_clarify_line(match.group(1))
        if ":" in body:
            ask, rest = body.split(":", 1)
            options = [_strip_option(part) for part in re.split(r"\s*/\s*", rest) if _strip_option(part)]
        else:
            ask, options = body, []
        ask = ask.strip()
        if len(ask) < 6 or _is_technical_clarify_question(ask):
            continue
        if not (_looks_like_scope_question(ask) or options):
            continue
        if "?" not in ask:
            ask = ask.rstrip(".") + "?"
        items.append(OpenQuestion(id="", question=ask, options=options[:4]))
        if len(items) >= 5:
            break
    return items


def _strip_option(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = cleaned.lstrip("-•*").strip()
    cleaned = re.sub(r"^\d+[.)]\s*", "", cleaned).strip()
    return cleaned


def build_plan_prompt(
    *,
    document_text: str,
    document_name: str = "",
    image_count: int = 0,
    attachment_names: list[str] | None = None,
) -> str:
    name = document_name or "files"
    clipped = document_text.strip()
    if len(clipped) > 80_000:
        clipped = clipped[:80_000] + "\n\n[...truncated...]"
    names = attachment_names or []
    names_line = ", ".join(names) if names else "—"
    vision_line = (
        f"К этому сообщению приложено изображений: {image_count}. "
        "Учитывай их содержимое в плане наравне с текстом.\n"
        if image_count
        else ""
    )
    body = clipped if clipped else "(текстовых материалов нет — опирайся на приложенные изображения)"
    return (
        "Ты планировщик реализации. Загруженные файлы, изображения и заметки — источник требований.\n"
        "Составь план внедрения и критерии проверки.\n"
        "Не пиши код. Технические детали (поля, справочники, инструменты) выясни сам; "
        "у человека спрашивай только смысл работы агента.\n\n"
        f"Источник: {name}\n"
        f"Файлы: {names_line}\n"
        f"{vision_line}\n"
        "===== MATERIALS START =====\n"
        f"{body}\n"
        "===== MATERIALS END =====\n\n"
        f"{PLAN_SCHEMA_HINT}"
    )


def build_clarify_prompt(
    *,
    answers: dict[str, str],
    plan: WorkflowPlan,
    image_count: int = 0,
    image_names: list[str] | None = None,
) -> str:
    lines = ["Пользователь ответил на открытые вопросы. Обнови план."]
    if image_count:
        names = ", ".join(image_names or []) or "—"
        lines.append(
            f"К этому сообщению приложено изображений: {image_count} ({names}). "
            "Прочитай текст/таблицы/списки со скриншотов и используй их в answers и плане. "
            "Не говори, что файл недоступен, если изображение приложено к запросу."
        )
    for q in plan.open_questions:
        ans = (answers.get(q.id) or q.answer or "").strip()
        lines.append(f"- {q.id}: {q.question}\n  answer: {ans or '(пусто)'}")
    lines.append("")
    lines.append("Текущий план (JSON):")
    lines.append(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    lines.append("")
    lines.append(
        "Верни обновлённый план в той же JSON-схеме. "
        "Заполни answer у вопросов этого хода. "
        "answered_questions — полный список ВСЕХ ответов (прошлые + новые). "
        "Если пользователь написал «не знаю / выясни сам / определи сам» — "
        "это ответ: агент сам найдёт поля, справочники и числа через tools. "
        "НЕ задавай новые вопросы по той же теме (имена полей, N дней, коды 1С). "
        "Новый вопрос — только если без решения человека нельзя понять цель "
        "(кому писать, уведомление или отчёт, как часто). Максимум 2 новых. "
        "Вопросы простыми словами, options — действия, не инструменты. "
        "НЕ спрашивай URL, логин, OData/COM/IMAP/fixtures. "
        "Не повторяй уже закрытую тему с другим id. "
        "Если критичных человеческих решений больше нет — open_questions: [] "
        "и обнови steps/runtime. runtime.kind по ответам."
    )
    lines.append(PLAN_SCHEMA_HINT)
    return "\n".join(lines)


ARTIFACTS_INSTRUCTION = (
    "ВАЖНО (доставка результата без git): создай в рабочем пространстве каталог "
    "`artifacts/` и скопируй туда ВСЕ итоговые файлы. Без файлов в `artifacts/` "
    "пользователь скачает пустую папку — текст в чате не считается файлом.\n"
    "- `artifacts/RESULT.md` — обязателен: предметный вывод live-инструментов плана "
    "(таблица или список того, что вернул tool; поля — из ответа инструмента / плана, "
    "не выдумывай колонки) и итоговая строка `TESTS: PASS` или `TESTS: FAIL`.\n"
    "- `artifacts/solution.zip` — архив написанного кода/проекта;\n"
    "- сгенерированные выходные файлы (.xlsx/.csv/.pdf и т.п.), если они есть.\n"
    "Клади готовые файлы именно в `artifacts/` (пути относительные)."
)

LIVE_TOOLS_TEST_INSTRUCTION = (
    "Тестовый прогон (обязательно):\n"
    "- ```constructor_tool — это НЕ инструмент Cursor и НЕ HTTP с VM. "
    "Это markdown-блок в твоём сообщении. Constructor перехватывает блок и "
    "сам вызывает tool на сервере. Писать «не могу вызвать constructor_tool» запрещено.\n"
    "- ПЕРВЫЙ ответ в execute — ТОЛЬКО один блок (без кода, fixtures, RESULT.md):\n"
    "```constructor_tool\n"
    '{"name": "turboproject", "arguments": {}}\n'
    "```\n"
    "Подставь `name` из каталога/плана. Дождись фактов, потом пиши код.\n"
    "- ЗАПРЕЩЕНО: `BACKEND_URL`, curl, прямой HTTP с Cloud VM. "
    "Нет `BACKEND_URL` на VM — норма, не FAIL.\n"
    "- `artifacts/RESULT.md` — предметный вывод того, что вернул tool "
    "(поля из ответа / плана) + `TESTS: PASS|FAIL`.\n"
    "- `TESTS: PASS` только после ответа Constructor tool. "
    "Запрещено PASS за код/fixtures без вызова tool.\n"
    "- После пустого/ошибочного ответа — снова только ```constructor_tool.\n"
    "- `TESTS: FAIL` только если tool дважды вернул ошибку или его нет в каталоге."
)

RESULT_STATUS_INSTRUCTION = (
    "Статус в RESULT.md и финальном ответе:\n"
    "- Не пиши «агент сформирован», «реализация завершена», «можно сохранить», "
    "пока нет `TESTS: PASS` по полному прогону.\n"
    "- Если в плане есть live-источник — вызови его через ```constructor_tool. "
    "`TESTS: PASS` без вызова tool и без предметного вывода в RESULT.md запрещён.\n"
    "- Нет `BACKEND_URL` на Cloud VM — ожидаемо, не FAIL. Не ходи в 1С/TurboProject "
    "с VM по HTTP. Live = Constructor tools на сервере.\n"
    "- Если live-инструмент плана ответил (данные или честная пустая выборка) — "
    "`TESTS: PASS`.\n"
    "- `TESTS: FAIL` только после ошибки Constructor tool (повторы исчерпаны) "
    "или если инструмента нет в каталоге. Не за сеть Cloud VM, не за INVOKER, "
    "не за отсутствие URL в чате.\n"
    "- При настоящем FAIL: заголовок «Тестовый прогон не завершён», почему "
    "цель недостижима. Не делай раздел «Что сделано», будто агент готов."
)

TESTS_USER_CLARIFY_INSTRUCTION = (
    "Тесты и тупики:\n"
    "- ЗАПРЕЩЕНО спрашивать пользователя про 1С, OData, COM, fixtures, INVOKER, "
    "ONEC_BASE_URL, CONSTRUCTOR_API_URL, логин/пароль, «как продолжить live». "
    "Не пиши блок CLARIFY по доступу к 1С/почте/API — бери рекомендованный путь сам.\n"
    "- Рекомендовано для 1С: сначала `onec.odata_catalog` (документы/справочники/регистры), "
    "затем `onec.odata_get` с entity из каталога и/или `onec.sql_query`. "
    "Задачи пользователя из erp_pm и документооборота: `onec.erp_tasks_current` "
    "(открытые сейчас) и `onec.erp_tasks_period` (за период, date_from/date_to YYYY-MM-DD). "
    "Только документооборот: `onec.docflow_tasks`. "
    "Проекты MS Project + 1С: `turboproject` (поля — из ответа инструмента). "
    "Задачи подчинённых руководителя: `onec.erp_subordinate_tasks` "
    "(сначала прямые подчинённые и их задачи/сроки за date_from…date_to, "
    "затем подчинённые каждого из них; человек из JWT). "
    "ФИО берётся из JWT сессии — не спрашивай ФИО и не передавай его, "
    "если не нужна чужая карточка. "
    "Учётка уже на сервере. Не ходи в 1С/TurboProject прямым HTTP с облачной VM.\n"
    "- Если `constructor_tool` вернул ошибку — вызови его ещё раз. "
    "Не подменяй live-вызов `--fixtures` и не ставь FAIL из-за Cloud VM.\n"
    "- CLARIFY допустим ТОЛЬКО по смыслу задачи (какой проект, какой отчёт), "
    "не по инфраструктуре. Не выдумывай INVOKER и не проси GUID/стенд у пользователя."
)

RUNTIME_NETWORK_INSTRUCTION = (
    "Сеть и прогоны:\n"
    "- Cloud VM часто НЕ достучится до закрытых площадок — это ожидаемо. "
    "Не ставь FAIL и не останавливайся: live идёт через ```constructor_tool, "
    "не через сеть VM и не через BACKEND_URL.\n"
    "- Реализуй ДВА режима в коде агента: `--fixtures` (офлайн/CI) и `--live` (боевой). "
    "Тестовый прогон в конструкторе = live через Constructor tools, не fixtures вместо tool.\n"
    "- Live-режим должен соответствовать ДОМЕНУ плана, а не универсальному web_search:\n"
    "  • совещания / Outlook / календарь → CLI/фикстуры / COM Outlook / Graph, "
    "если пользователь так указал в ответах; "
    "НЕ DuckDuckGo/web_search и НЕ site_browser «открыть outlook.office.com»;\n"
    "  • 1С — tools `onec.*` (OData/SQL с сервера) или COM на машине пользователя, не web_search; "
    "задачи erp_pm и документооборота — `onec.erp_tasks_current` / `onec.erp_tasks_period` "
    "/ `onec.erp_subordinate_tasks` / `onec.docflow_tasks` (ФИО из JWT); "
    "проекты TurboProject — `turboproject`;\n"
    "  • поиск на сайте/ЭТП + Excel → site_browser / plan_export / HTTP к указанному site_url;\n"
    "  • общий веб-поиск фактов — только если это явно цель агента.\n"
    "- Фикстуры — для CLI/CI после публикации. Сейчас live = onec.* / turboproject / "
    "imap.* через Constructor, не прямой доступ с VM.\n"
    "- В RESULT.md опиши: какие тесты реально прогнаны, какой live-инструмент использован, "
    "доступен ли live, и как запускать агента локально.\n"
    "- Не подменяй предметную область агента на web_search «для галочки»."
)


def server_access_notes(*, odata: bool, imap: bool, turboproject: bool = False) -> str:
    odata_line = (
        "1С OData (tools onec.*): настроен в backend/.env. "
        "Не спрашивай пользователя. Live = onec.*, не HTTP с Cloud VM. "
        "Недоступность 1С с облака — не блокер и не FAIL."
        if odata
        else (
            "1С OData в backend/.env не задан. Для теста бери --fixtures, не спрашивай учётку в чате."
        )
    )
    imap_line = (
        "IMAP (tools imap.*): настроен в backend/.env."
        if imap
        else "IMAP: в backend/.env не настроен — не проси логин/пароль почты в чате."
    )
    turbo_line = (
        "TurboProject (tool turboproject): настроен в backend/.env."
        if turboproject
        else "TurboProject: в backend/.env не настроен — не проси логин API в чате."
    )
    return (
        "Доступы Constructor (не спрашивай секреты у пользователя):\n"
        f"- {odata_line}\n"
        f"- {imap_line}\n"
        f"- {turbo_line}\n"
        "- Не вызывай BACKEND_URL / CONSTRUCTOR_API_URL / curl с Cloud VM — "
        "на VM их нет, это не FAIL. Live только через ```constructor_tool.\n"
        "- Имена ONEC_BASE_URL / CONSTRUCTOR_API_URL в проекте нет — это ODATA_* на сервере."
    )


def build_execute_prompt(
    *,
    plan: WorkflowPlan,
    document_text: str,
    access_notes: str = "",
) -> str:
    plan_json = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    doc = document_text.strip()
    if len(doc) > 40_000:
        doc = doc[:40_000] + "\n\n[...truncated...]"
    answers_block = plan.answered_block_text()
    answers_section = f"\n{answers_block}\n\n" if answers_block else "\n"
    access_section = f"{access_notes.strip()}\n\n" if access_notes.strip() else ""
    return (
        "СНАЧАЛА live через Constructor, потом код.\n"
        "constructor_tool — markdown-блок в ответе, не tool Cursor. "
        "Первое сообщение: только ```constructor_tool с name из плана, без Python и fixtures.\n"
        "Реализуй сохранённый план без git/GitHub. Не расширяй scope.\n"
        "ОБЯЗАТЕЛЬНО учти answered_questions: если там 1С / TurboProject / COM — "
        "это live через Constructor tools, не web_search.\n"
        "В финальном ответе не называй агента готовым без TESTS: PASS.\n\n"
        f"{access_section}"
        f"{LIVE_TOOLS_TEST_INSTRUCTION}\n\n"
        f"{RESULT_STATUS_INSTRUCTION}\n\n"
        f"{RUNTIME_NETWORK_INSTRUCTION}\n\n"
        f"{TESTS_USER_CLARIFY_INSTRUCTION}\n\n"
        f"{ARTIFACTS_INSTRUCTION}\n"
        f"{answers_section}"
        "===== PLAN JSON =====\n"
        f"{plan_json}\n"
        "===== PLAN END =====\n\n"
        "===== ORIGINAL DOCUMENT (context) =====\n"
        f"{doc}\n"
        "===== DOCUMENT END ====="
    )


def build_reexecute_prompt(
    *,
    plan: WorkflowPlan,
    user_clarification: str = "",
    access_notes: str = "",
) -> str:
    plan_json = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    clarify_block = ""
    note = (user_clarification or "").strip()
    if note:
        clarify_block = (
            "\n\n===== УТОЧНЕНИЕ ПОЛЬЗОВАТЕЛЯ (после TESTS: FAIL) =====\n"
            f"{note}\n"
            "Учти этот ответ: закрой блокер, обнови конфиг/фикстуры/live-проверку "
            "и снова выставь TESTS: PASS|FAIL в RESULT.md.\n"
            "===== КОНЕЦ УТОЧНЕНИЯ =====\n"
        )
    answers_block = plan.answered_block_text()
    answers_section = f"\n{answers_block}\n" if answers_block else ""
    access_section = f"{access_notes.strip()}\n\n" if access_notes.strip() else ""
    return (
        "СНАЧАЛА live: только markdown ```constructor_tool (это не tool Cursor). "
        "Не пиши, что нет доступа к constructor_tool.\n"
        "Потом доведи план без GitHub. Не ломай уже корректное.\n"
        "Интеграции из ответов (1С / TurboProject / COM) — через Constructor tools, не web_search.\n"
        "В конце — статус PASS/FAIL по критериям (TESTS: PASS|FAIL в RESULT.md). "
        "Не пиши, что агент готов, без TESTS: PASS.\n\n"
        f"{access_section}"
        f"{LIVE_TOOLS_TEST_INSTRUCTION}\n\n"
        f"{RESULT_STATUS_INSTRUCTION}\n\n"
        f"{RUNTIME_NETWORK_INSTRUCTION}\n\n"
        f"{TESTS_USER_CLARIFY_INSTRUCTION}\n\n"
        f"{ARTIFACTS_INSTRUCTION}\n"
        f"{answers_section}"
        f"{clarify_block}\n"
        f"{plan_json}"
    )


def _extract_json_blob(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()

    # fenced ```json
    fence = "```"
    if fence in stripped:
        parts = stripped.split(fence)
        for i, chunk in enumerate(parts):
            if i % 2 == 1:
                body = chunk
                if body.lstrip().lower().startswith("json"):
                    body = body.lstrip()[4:]
                body = body.strip()
                try:
                    data = json.loads(body)
                    if isinstance(data, dict):
                        return data
                except json.JSONDecodeError:
                    continue

    # raw object
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        candidate = stripped[start : end + 1]
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return None


def parse_plan_from_text(text: str) -> WorkflowPlan:
    data = _extract_json_blob(text)
    if not data:
        return WorkflowPlan(
            title="План (неструктурированный)",
            goal=text[:500] if text else "",
            raw_text=text,
            open_questions=[
                OpenQuestion(
                    id="q_parse",
                    question="Агент не вернул JSON-план. Уточните цель одной фразой или приложите требования ещё раз.",
                    why="Нужна структура для последующего выполнения",
                )
            ],
        )

    plan = WorkflowPlan.from_dict(data)
    plan.raw_text = text
    if not plan.steps and not plan.goal:
        plan.goal = str(data.get("summary") or data.get("description") or "")[:1000]
    # normalize empty ids
    for i, step in enumerate(plan.steps):
        if not step.id:
            step.id = f"s{i + 1}"
    for i, q in enumerate(plan.open_questions):
        if not q.id:
            q.id = f"q{i + 1}"
    return plan


def plan_summary_text(plan: WorkflowPlan) -> str:
    lines = [
        f"# {plan.title or 'План'}",
        "",
        f"**Цель:** {plan.goal or '—'}",
        "",
    ]
    if plan.constraints:
        lines.append("**Ограничения:**")
        lines.extend(f"- {c}" for c in plan.constraints)
        lines.append("")
    if plan.out_of_scope:
        lines.append("**Вне scope:**")
        lines.extend(f"- {c}" for c in plan.out_of_scope)
        lines.append("")
    if plan.steps:
        lines.append("**Шаги:**")
        for step in plan.steps:
            dep = f" (depends: {', '.join(step.depends_on)})" if step.depends_on else ""
            lines.append(f"- `{step.id}` {step.title}{dep}")
            if step.action:
                lines.append(f"  - {step.action}")
            if step.done_when:
                lines.append(f"  - done when: {step.done_when}")
        lines.append("")
    if plan.test_criteria:
        lines.append("**Тесты:**")
        lines.extend(f"- {c}" for c in plan.test_criteria)
        lines.append("")
    unanswered = plan.unanswered()
    if unanswered:
        lines.append("**Открытые вопросы:**")
        for q in unanswered:
            lines.append(f"- `{q.id}` {q.question}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_kpi_curator_prompt(
    *,
    title: str,
    goal: str,
    plan_text: str,
    schedule_draft: dict[str, Any] | None = None,
    notes: str = "",
) -> str:
    schedule = json.dumps(schedule_draft or {}, ensure_ascii=False, indent=2)
    return f"""
Ты куратор KPI для ИИ-агента Constructor. По паспорту и расписанию определи,
как агент ДОЛЖЕН работать (план) и напиши методику расчёта факта.

Агент:
- Название: {title or "—"}
- Цель: {goal or "—"}
- Заметки: {(notes or "—")[:1200]}
- Расписание / триггеры:
{schedule}

План агента:
{plan_text or "—"}

Верни ТОЛЬКО один JSON-объект (можно в блоке ```json), без текста вокруг.
Схема:
{{
  "summary": "как должен работать агент: частота, что считает успехом",
  "tiles": [
    {{
      "id": "snake_case",
      "name": "человеческое имя KPI",
      "plan": {{
        "label": "План",
        "value": 30,
        "unit": "мин",
        "description": "как ДОЛЖЕН работать"
      }},
      "fact": {{
        "label": "Факт",
        "value": null,
        "unit": "%",
        "description": "как измерять факт"
      }},
      "measure": {{
        "kind": "expected_interval",
        "params": {{}},
        "formula": "человеческая формула"
      }},
      "method": {{
        "how": "как считать факт по истории прогонов",
        "when": "когда считать: периодичность или дата",
        "plan_update": "когда обновлять план",
        "fact_update": "когда обновлять факт",
        "percent_formula": "как считать KPI в процентах 0–100",
        "green_min": 90,
        "yellow_min": 70,
        "schedule": {{
          "kind": "interval",
          "interval_seconds": 3600,
          "at": ""
        }}
      }}
    }}
  ]
}}

Правила:
- 3–5 плиток, без повторов measure.kind.
- measure.kind только из: expected_interval, runs_count, success_rate, on_schedule_rate, fail_count.
- У каждой плитки обязательна method: как считать, когда считать, когда обновлять план и факт, как считать процент.
- green_min / yellow_min — пороги цвета: % >= green_min зелёный, % >= yellow_min жёлтый, иначе красный. yellow_min < green_min.
- schedule.kind: interval (повторять каждые interval_seconds) или at (однократно в at ISO).
- План — норма работы (частота, 100% успешности, 0 ошибок).
- fact.value и score_percent всегда null: значения посчитает фоновый агент по методике.
- Если запусков ещё нет, факт читается как «ещё нет прогонов».
- Не выдумывай поля TurboProject и не пиши произвольный код.
- Не вызывай constructor_tool и не ходи в HTTP — только JSON.
""".strip()


def build_kpi_calc_prompt(
    *,
    title: str,
    goal: str,
    plan_text: str,
    schedule_draft: dict[str, Any] | None = None,
    tiles: list[dict[str, Any]] | None = None,
    runs: list[dict[str, Any]] | None = None,
) -> str:
    context = json.dumps(
        {
            "title": title or "",
            "goal": goal or "",
            "schedule": schedule_draft or {},
            "tiles": tiles or [],
            "runs": runs or [],
        },
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    return f"""
Ты считаешь KPI ИИ-агента Constructor по уже утверждённой методике каждой плитки.
Не меняй методику и пороги. Посчитай план (если методика велит обновить), факт и score_percent.

Краткий план агента:
{plan_text or "—"}

Контекст (плитки к расчёту и история прогонов):
{context}

Верни ТОЛЬКО один JSON-объект (можно в блоке ```json), без текста вокруг.
Схема:
{{
  "tiles": [
    {{
      "id": "id плитки из контекста",
      "plan": {{"value": 30, "unit": "мин", "description": ""}},
      "fact": {{"value": 28, "unit": "мин", "description": ""}},
      "score_percent": 93.3,
      "evidence": "какие прогоны, интервалы и статусы вошли в расчёт"
    }}
  ]
}}

Правила:
- Считай только плитки из контекста, id не выдумывай.
- Следуй method.how, method.percent_formula, method.plan_update и method.fact_update.
- score_percent — KPI в процентах 0–100 по percent_formula.
- evidence — кратко, по каким данным получились план, факт и процент (id/время/статусы прогонов, интервалы).
- Если прогонов нет или данных недостаточно: fact.value = null, score_percent = null, evidence = «ещё нет прогонов».
- Не вызывай constructor_tool и не ходи в HTTP — только JSON.
""".strip()


