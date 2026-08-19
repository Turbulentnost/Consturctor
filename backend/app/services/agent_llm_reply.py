"""Финальный ответ агента через LLM — не шаблон, а осмысленный текст с границами UI."""

from __future__ import annotations

from typing import Any

from app.models.workflow import Workflow

_HANDLER_UI: dict[str, str] = {
    "act_porucheniya_registry": (
        "ACT-реестр: по задаче — выгрузка OData→Excel, сводка по указанному .xlsx на рабочем столе, "
        "или ответ в чате без нового Excel (фильтры, ACT00-***). "
        "Произвольные сообщения («привет», опечатки) — только ответ в чате, без OData. "
        "«Обнови excel» — пересохранение файла с рабочего стола (без OData, если файл есть). "
        "Дополнение: «добавь/дополни задачу», протокол или --- ПРОТОКОЛ --- — "
        "база берётся из Excel на рабочем столе (без OData), затем пересохранение. "
        "Строки из протокола — в колонке «Статус»; цвет строки по сроку задачи (критичность)."
    ),
    "assignments_smart": "Проверка SMART-формулировок поручений (если включён маршрут).",
    "assignments_action_tracker": "Контроль исполнения поручений (если включён маршрут).",
    "site_search_excel": "Поиск по сайту/ключам и Excel по правилам из плана агента.",
    "outlook_calendar": "Чтение почты и календаря Outlook на этом ПК.",
    "browser_task": "Открытие сайтов и сбор данных через браузер на этом ПК.",
    "generic": "Универсальный агент: поиск в интернете или на указанном сайте.",
}

_DESKTOP_UI = """
Интерфейс turbobot (desktop), что видит пользователь:
• Лента диалога — ваши сообщения и ответы агента.
• Кнопка «Запустить типовую задачу» — подставляет задачу из настроек workflow.
• Поле ввода и «➤» — своя формулировка задачи.
• Боковая панель «Статус» — этап выполнения (OData, Excel, LLM…).
• Excel и файлы появляются на рабочем столе Windows (не во вкладке приложения).

Через UI нельзя: править код агента, открыть терминал, менять маршрут handler,
публиковать workflow на сервере — только запуск готового агента и чтение результата.
"""


def finalize_agent_answer(
    *,
    task: str,
    handler: str,
    workflow: Workflow,
    factual_answer: str,
    extra_context: dict[str, Any] | None = None,
    emit: Any = None,
) -> str:
    """Обогатить технический отчёт ответом LLM; при недоступности LLM — отчёт + пояснение."""
    from app.services.llm_provider import effective_llm_provider, llm_ready
    from app.services import runtime_llm

    factual = (factual_answer or "").strip()
    if not factual:
        factual = "Задача выполнена, но итоговых данных нет."

    if extra_context and str(extra_context.get("odata_source") or "") == "odata-error":
        return factual

    if not llm_ready():
        return factual + _llm_unavailable_footer(effective_llm_provider())

    if emit is not None:
        emit({"type": "status", "text": "Формирую ответ через LLM…"})
        emit(
            {
                "type": "thinking",
                "text": f"LLM ({effective_llm_provider()}): анализ результата и формулировка ответа…",
            }
        )

    system = _system_prompt(handler=handler, workflow=workflow)
    prompt = _user_prompt(task=task, factual_answer=factual, extra_context=extra_context)
    reply = runtime_llm.generate(prompt, system=system, max_tokens=1200, quick=True)
    if reply and reply.strip():
        return reply.strip()

    err = runtime_llm.last_error() or "нет ответа"
    return factual + f"\n\n—\nНе удалось получить ответ LLM ({err}). Выше — технический отчёт."


def _llm_unavailable_footer(provider: str) -> str:
    return (
        f"\n\n—\nLLM сейчас недоступен (провайдер: {provider}). "
        "Задайте CURSOR_API_KEY и LLM_PROVIDER=cursor в infra/.env и перезапустите backend."
    )


def _system_prompt(*, handler: str, workflow: Workflow) -> str:
    h = (handler or "generic").casefold()
    capability = _HANDLER_UI.get(h) or _HANDLER_UI["generic"]
    title = str(workflow.title or "").strip() or "ИИ-агент"
    return (
        "Ты — ИИ-ассистент платформы Constructor (turbobot). Отвечай на русском, "
        "деловым тоном, от первого лица («я выгрузила», «могу», «не могу»).\n"
        f"{_DESKTOP_UI}\n"
        f"Этот агент («{title}»), handler={h}:\n{capability}\n"
        "Правила ответа:\n"
        "1. Опирайся только на блок «Фактический результат» — не выдумывай цифры и файлы.\n"
        "2. Кратко: что сделано, сколько записей, путь к Excel (если есть).\n"
        "3. Отдельным абзацем «Что могу из этого экрана» — 2–4 пункта по UI.\n"
        "4. Отдельным абзацем «Чего не могу из UI» — 1–3 пункта (код, routing, публикация…).\n"
        "5. Если данных 0 или ошибка OData/COM — объясни возможную причину и что проверить.\n"
        "6. При ошибке OData (timed out, HTTP) — это сбой связи с 1С, не «пустая база», "
        "если в факте указано OData error.\n"
        "7. Цвет строк Excel — только по критичности срока; не упоминай «голубые» строки.\n"
        "8. Строки из протокола отличаются колонкой «Статус» («Из протокола»), не цветом.\n"
        "9. Без markdown-заголовков #, без JSON, без списка инструментов API."
    )


def _user_prompt(
    *,
    task: str,
    factual_answer: str,
    extra_context: dict[str, Any] | None,
) -> str:
    lines = [
        f"Задача пользователя:\n{(task or '').strip() or '(типовая задача)'}",
        f"\nФактический результат выполнения:\n{factual_answer}",
    ]
    if extra_context:
        excel = extra_context.get("excel_path") or extra_context.get("excel")
        if excel:
            lines.append(f"\nФайл Excel: {excel}")
        count = extra_context.get("count")
        if count is not None:
            lines.append(f"\nДокументов ACT (после фильтра): {count}")
        task_count = extra_context.get("task_count")
        if task_count is not None:
            lines.append(f"Задач в табличной части «Поручения»: {task_count}")
        total = extra_context.get("total_count")
        if total is not None and total != count:
            lines.append(f"Всего в OData: {total}")
        filt = extra_context.get("filter")
        if filt:
            lines.append(f"\nПрименённый фильтр: {filt}")
        att = extra_context.get("attachment_context")
        if att:
            lines.append(f"\nКонтекст из вложений workflow:\n{att}")
        odata_source = extra_context.get("odata_source")
        if odata_source:
            lines.append(f"\nИсточник OData: {odata_source}")
        odata_summary = extra_context.get("odata_summary")
        if odata_summary:
            lines.append(f"Сводка OData: {odata_summary}")
    lines.append(
        "\nСформулируй итоговый ответ для пользователя в приложении. "
        "Для ACT-реестра: предложи 1–2 примера следующих сообщений в чат "
        "(например «только просроченные», «добавь колонку …»)."
    )
    return "\n".join(lines)
