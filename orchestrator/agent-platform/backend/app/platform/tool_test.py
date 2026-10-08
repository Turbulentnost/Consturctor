"""Тестовый запуск инструмента: служебный агент платформы проверяет поля одного инструмента и вызывает его.

Запуск не сохраняется: сессия живёт в памяти (ephemeral), в общую историю и списки не попадает.
Вызов инструмента, который меняет данные, MCP-сервер тестировщика выполняет только после
разрешения человека — это проверка в коде, а не просьба к модели.
"""

from __future__ import annotations

import json

from app.tools.registry import ToolSpec

TESTER_CONFIG_ID = "tool-tester"

SIDE_EFFECTS = {
    "read": "только читает данные",
    "create_draft": "создаёт черновик",
    "write": "изменяет данные",
    "dangerous": "опасное действие",
}


def needs_permission(spec: ToolSpec) -> bool:
    return spec.side_effect != "read" or spec.requires_approval


def _card(spec: ToolSpec) -> str:
    card = {
        "name": spec.name,
        "title": spec.title,
        "group": spec.group,
        "summary": spec.summary,
        "description": spec.description,
        "input_schema": spec.input_schema,
        "execution": spec.execution,
        "runtime": spec.runtime,
        "side_effect": spec.side_effect,
        "requires_approval": spec.requires_approval,
        "timeout_seconds": spec.timeout_seconds,
        "requires": spec.requires,
        "replaces": spec.replaces,
        "source": spec.source.model_dump() if spec.source else None,
        "available": spec.available,
        "unavailable_reason": spec.unavailable_reason,
    }
    return json.dumps(card, ensure_ascii=False, indent=2)


def tool_test_prompt(spec: ToolSpec) -> str:
    permission = (
        f"Инструмент {SIDE_EFFECTS.get(spec.side_effect, spec.side_effect)}"
        f"{' и требует подтверждения' if spec.requires_approval else ''}. Каждый его вызов платформа "
        "сначала показывает человеку и выполняет только после «Разрешить». Перед вызовом одной "
        "фразой напиши, что и с какими данными собираешься сделать. Если человек отклонил вызов — "
        "не повторяй его с теми же данными и продолжай проверку без него."
        if needs_permission(spec)
        else "Инструмент только читает данные — вызывай его без подтверждения."
    )
    return "\n\n".join(
        [
            f"Протестируй инструмент платформы TurboTester `{spec.name}`"
            f"{f' («{spec.title}»)' if spec.title else ''}. Он подключён к тебе MCP-инструментом "
            "сервера tester; кроме него у тебя есть только чтение файлов и вопросы человеку.",
            f"Карточка инструмента из каталога платформы:\n```json\n{_card(spec)}\n```",
            "## Что проверить\n"
            "1. Поля карточки. Схема параметров — корректная JSON Schema: у каждого параметра есть тип "
            "и понятное описание, все `required` есть в `properties`, `enum` и `default` согласованы "
            "с типом. Описание для LLM совпадает со схемой и объясняет, когда и как вызывать "
            "инструмент. `side_effect` и `requires_approval` соответствуют тому, что инструмент делает. "
            "Таймаут разумный, требования (`requires`) и доступность указаны.\n"
            "2. Работа. Составь реалистичные аргументы по схеме и вызови инструмент: обычный случай, "
            "затем один-два граничных (без необязательных полей, пустое или неверное значение) — "
            "по ним видно, как инструмент сообщает об ошибках. Если для проверки нужны настоящие "
            "данные, которых нет в карточке (идентификатор, адрес, номер документа), спроси человека "
            "через ask_user, а не выдумывай. Если ответ инструмента — `status: waiting_permission` или "
            "`status: running`, сразу вызови wait_call с его call_id и больше ничего не делай.\n"
            f"3. Безопасность. {permission}",
            "## Отчёт\n"
            "В конце дай отчёт в markdown:\n"
            "- **Итог** — одной строкой: работает / работает с замечаниями / не работает.\n"
            "- **Поля инструмента** — найденные проблемы карточки; если их нет, так и напиши.\n"
            "- **Проверочные вызовы** — для каждого: аргументы, результат или ошибка, время.\n"
            "- **Ошибки и как исправить** — по каждой ошибке причина и конкретная рекомендация: что "
            "поменять в схеме, описании, паспорте (`backend/app/tools/passports.py`) или реализации "
            f"({spec.source.path if spec.source else 'файл реализации'}), какие настройки или доступы "
            "добавить.",
        ]
    )
