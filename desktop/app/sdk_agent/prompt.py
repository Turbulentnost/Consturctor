from __future__ import annotations

from app.api_client import WorkflowRecord


def build_design_sdk_prompt(workflow: WorkflowRecord, design_prompt: str) -> str:
    prompt = (design_prompt or "").strip()
    if prompt:
        return "\n".join(
            [
                "Ты локальный Cursor SDK агент Constructor.",
                "Сформируй план достижения цели по паспорту агента.",
                "Показывай ход проектирования в ответе так, как это делает Cursor: коротко, по делу, шаг за шагом.",
                "Финальный результат всё равно должен содержать пригодный JSON-черновик по схеме ниже.",
                "",
                prompt,
            ]
        )
    return build_sdk_prompt(
        workflow,
        "Спроектируй инструкцию агента: сформируй план достижения цели и верни JSON-черновик шагов.",
    )


def build_sdk_prompt(workflow: WorkflowRecord, user_message: str) -> str:
    plan = workflow.plan
    parts: list[str] = [
        "Ты локальный ИИ-агент Constructor.",
        "Работай только по паспорту агента и используй доступные tools, когда нужны живые данные.",
        "Не пиши JSON вызова инструмента в чат. Вызывай настоящий tool.",
        "Не используй shell/edit/write для работы с проектом: бизнес-результат должен прийти из tools и рассуждения.",
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
