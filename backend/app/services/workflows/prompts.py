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
- open_questions — только НЕотвеченные блокеры; иначе [].
- Если ответ пользователя неясен, противоречив или недостаточен для реализации —
  НЕ делай вид, что понял. Задай 1 уточняющий вопрос в open_questions + 2–4 options.
  Оценивай по смыслу и достаточности для steps/runtime, а НЕ по длине:
  короткий ответ («COM», «Graph», «1С ERP») может быть вполне информативным.
  Переспрашивай только если не хватает факта для реализации (способ доступа,
  URL, права, критерий, противоречие). Не переспрашивай «на всякий случай».
  Не переходи к пустым open_questions, пока критичный ответ реально размыт
  («как обычно», «ок», пусто, противоречие без выбора).
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
        "Если ответ НЕДОСТАТОЧЕН для реализации по смыслу — задай уточняющий вопрос "
        "в open_questions (один главный, с options). Оценивай достаточность, не длину: "
        "«COM», «Graph», «1С» могут быть нормальным ответом на вопрос «какой способ». "
        "Переспрашивай, только если не хватает конкретного факта "
        "(какая база 1С, OData URL, чья учётка, confirm перед записью и т.п.). "
        "Не принимай молча заглушки вроде «ок» / «как обычно» / пусто. "
        "open_questions оставляй пустым, если ответы достаточны для steps/runtime. "
        "Перенеси понятные ответы в constraints и steps: интеграция должна совпадать "
        "с ответами (COM Outlook, 1С/OData и т.п. — не подменяй на web_search/site_browser). "
        "runtime.kind ставь по ответам: outlook_calendar / onec / site_search_excel / browser_task."
    )
    lines.append(PLAN_SCHEMA_HINT)
    return "\n".join(lines)


ARTIFACTS_INSTRUCTION = (
    "ВАЖНО (доставка результата без git): создай в рабочем пространстве каталог "
    "`artifacts/` и скопируй туда ВСЕ итоговые файлы, чтобы их можно было скачать:\n"
    "- `artifacts/solution.zip` — архив всего написанного кода/проекта;\n"
    "- сгенерированные выходные файлы (например, .xlsx/.csv/.pdf), если они есть;\n"
    "- `artifacts/RESULT.md` — краткое описание: что сделано, как запустить, что внутри;\n"
    "  в RESULT.md обязательно итоговая строка `TESTS: PASS` или `TESTS: FAIL`.\n"
    "Клади готовые файлы именно в `artifacts/` (пути должны быть относительными)."
)

TESTS_USER_CLARIFY_INSTRUCTION = (
    "Тесты и тупики:\n"
    "- Если что-то не получается (нет доступа, SSO, неизвестный URL/учётка, "
    "неясный критерий, не хватает данных) — НЕ маскируй это под PASS и НЕ уходи "
    "в чужой инструмент «для галочки».\n"
    "- В RESULT.md поставь `TESTS: FAIL`, коротко опиши БЛОКЕР человеческим языком "
    "и в конце добавь блок для чата конструктора.\n"
    "- QUESTION обязан называть объект: URL *чего*, доступ *к чему*, учётка *какой системы*. "
    "Плохо: «дайте доступ», «укажите URL». "
    "Хорошо: «Укажите URL OData базы 1С (ONEC_BASE_URL)» / "
    "«Как дать доступ к Outlook: COM или Graph?».\n"
    "- В why/блокере покажи, ЧЕГО не хватило (цитата из ошибки / missing env).\n"
    "Формат:\n"
    "CLARIFY:\n"
    "QUESTION: <конкретный вопрос фактом>\n"
    "OPTIONS:\n"
    "- <вариант 1 — действие/факт>\n"
    "- <вариант 2>\n"
    "- <вариант 3>\n"
    "- Если пользователь уже отвечал, но ответ размытый — задай УТОЧНЯЮЩИЙ вопрос "
    "(что именно непонятно), а не повторяй тот же общий вопрос.\n"
    "- Пользователь ответит в чате конструктора (радиокнопки / свой вариант) — "
    "после ответа реализацию можно доработать. Уточнения — нормальный шаг теста, не провал."
)

RUNTIME_NETWORK_INSTRUCTION = (
    "Сеть и прогоны:\n"
    "- Cloud VM часто НЕ достучится до закрытых площадок / внутренних сайтов "
    "(Connection reset) — это ожидаемо, не считай задачу проваленной только из‑за этого.\n"
    "- Реализуй ДВА режима: `--fixtures` (офлайн/CI) и `--live` (боевой).\n"
    "- Live-режим должен соответствовать ДОМЕНУ плана, а не универсальному web_search:\n"
    "  • совещания / Outlook / календарь → CLI/фикстуры / COM Outlook / Graph, "
    "если пользователь так указал в ответах; "
    "НЕ DuckDuckGo/web_search и НЕ site_browser «открыть outlook.office.com»;\n"
    "  • 1С — OData/COM/учётка из ответов пользователя, не web_search;\n"
    "  • поиск на сайте/ЭТП + Excel → site_browser / plan_export / HTTP к указанному site_url;\n"
    "  • общий веб-поиск фактов — только если это явно цель агента.\n"
    "- Фикстуры — запасной путь для тестов; live проверяет тот же сценарий, что в steps.\n"
    "- В RESULT.md опиши: какие тесты реально прогнаны, какой live-инструмент использован, "
    "доступен ли live, и как запускать агента локально.\n"
    "- Не подменяй предметную область агента на web_search «для галочки»."
)


def build_execute_prompt(*, plan: WorkflowPlan, document_text: str) -> str:
    plan_json = json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)
    doc = document_text.strip()
    if len(doc) > 40_000:
        doc = doc[:40_000] + "\n\n[...truncated...]"
    answers_block = plan.answered_block_text()
    answers_section = f"\n{answers_block}\n\n" if answers_block else "\n"
    return (
        "Реализуй сохранённый план без доступа к git/GitHub:\n"
        "опиши реализацию, артефакты, команды/проверки и результат по test_criteria.\n"
        "Следуй steps по порядку зависимостей. Не расширяй scope.\n"
        "ОБЯЗАТЕЛЬНО учти все ответы пользователя (answered_questions / уточнения): "
        "если там 1С, COM Outlook, URL, учётка — реализуй именно это, "
        "не подменяй на web_search или site_browser.\n"
        "В финальном ответе кратко: что сделано, результаты проверок, что осталось.\n\n"
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


def build_reexecute_prompt(*, plan: WorkflowPlan, user_clarification: str = "") -> str:
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
    return (
        "Повторно выполни сохранённый план (без GitHub-репозитория).\n"
        "Не ломай уже корректное. Доведи незакрытые steps и test_criteria.\n"
        "ОБЯЗАТЕЛЬНО сохрани интеграции из ответов пользователя "
        "(1С / COM Outlook / указанные URL) — не подменяй на web_search.\n"
        "В конце — статус PASS/FAIL по критериям (TESTS: PASS|FAIL в RESULT.md).\n\n"
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

