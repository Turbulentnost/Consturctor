from __future__ import annotations

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


def build_design_sdk_prompt(workflow: WorkflowRecord, design_prompt: str) -> str:
    prompt = (design_prompt or "").strip()
    catalog = format_tool_catalog()
    header = [
        "Ты локальный Cursor SDK агент Constructor.",
        "Инструменты Constructor уже подключены как customTools (внутренний MCP custom-user-tools).",
        "Это не проектные MCP-серверы Cursor и не mcp.json репозитория.",
        "Не ищи MCP в проекте и не пиши, что MCP не найден: список инструментов ниже.",
        "На этапе проектирования бизнес-инструменты не вызывай: только знай, какие есть.",
        "Если в материалах нет расписания, периода, получателя или критерия успеха,",
        "сначала задай вопросы через SDK tool askQuestion с вариантами ответа.",
        "и обязательно заполни required_clarifications в JSON. Не выдумывай эти параметры.",
        "Показывай ход проектирования коротко, по делу, шаг за шагом.",
        "Финальный ответ после вопросов должен содержать пригодный JSON-черновик по схеме ниже.",
        "",
        "Доступные инструменты Constructor:",
        catalog,
    ]
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
        "Не используй shell/edit/write для работы с проектом: бизнес-результат должен прийти из tools и рассуждения.",
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
        "Выполни пробный прогон этого агента на реальных доступных tools. "
        "Проверь каждый шаг, сформируй устойчивую инструкцию для будущих повторных запусков. "
        "В ответе обязательно укажи WORK_RESULT, какие tools использованы, TESTS: PASS или TESTS: FAIL, "
        "и краткую инструкцию playbook для следующего запуска."
    )
    return build_sdk_prompt(workflow, task)
