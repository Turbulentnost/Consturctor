from __future__ import annotations

import json
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
- open_questions — все НЕотвеченные блокеры СРАЗУ (по одному факту на вопрос);
  иначе []. Пользователь ответит по очереди. Не оставляй «ещё спрошу потом».
- Пока open_questions не пуст: не анализируй реализацию подробно и не пиши
  готовые steps/test_criteria — только черновик названия/цели и список вопросов.
- Если агент про 1С / почту / календарь — на ЭТОМ этапе (план) сразу включи
  в open_questions вопросы с options: live или только fixtures; способ доступа
  (OData уже на сервере Constructor / COM на машине пользователя / офлайн).
  Не откладывай это на тестовый прогон и не совмещай с анализом.
- ЗАПРЕЩЕНО спрашивать URL, логин, пароль OData/IMAP и выдумывать
  ONEC_BASE_URL / CONSTRUCTOR_API_URL — учётка только в backend/.env сервера.
- Если ответ пользователя неясен, противоречив или недостаточен для реализации —
  НЕ делай вид, что понял. Добавь все недостающие уточнения в open_questions
  (каждый вопрос — один факт, 2–4 options). Не анализируй, пока есть вопросы.
  Оценивай по смыслу и достаточности для steps/runtime, а НЕ по длине:
  короткий ответ («COM», «Graph», «1С ERP», «только fixtures») может быть достаточным.
  Переспрашивай только если не хватает факта для реализации (способ доступа,
  live vs fixtures, критерий, противоречие). Не переспрашивай «на всякий случай»
  и не проси секреты. Не переходи к пустым open_questions, пока критичный ответ
  реально размыт («как обычно», «ок», пусто, противоречие без выбора).
- answered_questions — ВСЕ уже данные ответы пользователя (id/question/answer). Никогда не удаляй и не забывай прошлые ответы.
  Даже короткий ответ сохраняй как есть; если нужен follow-up — новым вопросом.
- options — 2-4 логичных варианта ответа на вопрос; не используй общие «Да/Нет», если нужен фактический источник, система, роль или срок.
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
        "Не пиши код. Не выдумывай факты, которых нет в материалах — задай вопрос.\n\n"
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
        "answered_questions — полный список ВСЕХ ответов пользователя (прошлые + новые); "
        "не выкидывай и не перефразируй ответы так, чтобы пропали факты "
        "(1С, COM, Outlook, URL, учётки, критерии). "
        "Если после ВСЕХ ответов этого хода всё ещё не хватает фактов — "
        "верни новые вопросы в open_questions (сразу все, по одному факту, с options) "
        "и не анализируй реализацию. Оценивай достаточность, не длину: "
        "«COM», «Graph», «1С», «только fixtures» могут быть нормальным ответом на вопрос «какой способ». "
        "Переспрашивай, только если не хватает режима (live/fixtures) или способа доступа "
        "(OData на сервере / COM / офлайн), критерия или есть противоречие. "
        "НЕ спрашивай URL, логин, пароль OData/IMAP и не выдумывай "
        "ONEC_BASE_URL / CONSTRUCTOR_API_URL — учётка в backend/.env. "
        "Не принимай молча заглушки вроде «ок» / «как обычно» / пусто. "
        "open_questions оставляй пустым ТОЛЬКО если ответы достаточны для steps/runtime — "
        "тогда обнови план. Пока есть вопросы, не пиши подробный анализ. "
        "Не повторяй вопрос, на который пользователь уже ответил по существу "
        "(даже другими словами или с новым id). "
        "Перенеси понятные ответы в constraints и steps: интеграция должна совпадать "
        "с ответами (COM Outlook, 1С/OData и т.п. — не подменяй на web_search/site_browser). "
        "runtime.kind ставь по ответам: outlook_calendar / onec / site_search_excel / browser_task."
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
как агент ДОЛЖЕН работать (план) и как измерять факт после прогонов.

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
      }}
    }}
  ]
}}

Правила:
- 3–5 плиток, без повторов measure.kind.
- measure.kind только из: expected_interval, runs_count, success_rate, on_schedule_rate, fail_count.
- План — норма работы (частота, 100% успешности, 0 ошибок).
- fact.value всегда null: значения посчитает backend по истории прогонов.
- Если запусков ещё нет, факт читается как «ещё нет прогонов».
- Не выдумывай поля TurboProject и не пиши произвольный код.
- Не вызывай constructor_tool и не ходи в HTTP — только JSON.
""".strip()


