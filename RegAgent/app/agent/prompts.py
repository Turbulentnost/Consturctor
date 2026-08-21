from __future__ import annotations

from app.attachment_text import format_attachments_block
from app.models import Card, UiSpec


def build_setup_prompt(*, regulation_text: str, file_name: str = "", clarifications: str = "") -> str:
    clip = regulation_text[:12000]
    if len(regulation_text) > 12000:
        clip += "\n\n[... текст обрезан ...]"
    clar_block = f"\n\n{clarifications.strip()}\n" if clarifications.strip() else ""
    return (
        "Ты проектируешь UI для desktop-приложения RegAgent.\n"
        "По регламенту нужно: кнопки действий, правила для агента, slash-команды чата.\n"
        "Если из регламента НЕЯСНО, как пользователь должен взаимодействовать — "
        "заполни needs_clarification (1–3 вопроса с options). Не выдумывай процессы.\n"
        "Если всё ясно — needs_clarification = [].\n\n"
        "Доступные инструменты на runtime:\n"
        "- Cursor SDK: read, grep, glob, shell, webSearch (ПК, браузер, файлы workspace)\n"
        "- custom: outlook.search_mail, outlook.read_calendar, outlook.create_event\n"
        "- custom: onec.docflow_tasks (OData, Документ.ТД_Поручения — основной источник поручений)\n"
        "- custom: onec.search_documents, onec.get_document_card, onec.search_tasks, "
        "onec.get_task_card, onec.meeting_service_notes (COM, не для ТД_Поручения)\n\n"
        "Верни ТОЛЬКО JSON (можно в ```json блоке) по схеме:\n"
        "{\n"
        '  "version": 1,\n'
        '  "title": "...",\n'
        '  "summary": "...",\n'
        '  "rules_prompt": "правила для агента из регламента",\n'
        '  "needs_clarification": [{"id":"...", "question":"...", "options":["..."], "allow_free_text": true}],\n'
        '  "actions": [{"id":"...", "label":"...", "hint":"...", "prompt":"...", "tools_hint":["..."]}],\n'
        '  "chat_commands": [{"command":"/...", "description":"..."}]\n'
        "}\n\n"
        f"Файл: {file_name or 'regulation'}\n"
        f"{clar_block}"
        "===== РЕГЛАМЕНТ =====\n"
        f"{clip}\n"
        "===== КОНЕЦ ====="
    )


def build_runtime_system(card: Card) -> str:
    spec = card.ui_spec
    actions = spec.actions
    lines = [
        "Ты агент RegAgent. Следуй rules_prompt.",
        "Для 1C и Outlook используй custom tool constructor_integrations (поля tool + arguments).",
        "Поручения 1С (Документ.ТД_Поручения, форма ОткрытьСписок): "
        "только constructor_integrations с tool=onec.docflow_tasks. Это OData erp_pm, "
        "включая табличную часть «Поручения». "
        "Не вызывай COM (onec.search_documents, onec.search_tasks, onec.get_document_card) "
        "и не ходи в 1С/OData через shell, curl или python.",
        "Для браузера, файлов и команд ПК — встроенные tools Cursor (shell, webSearch, read, edit).",
        "Отвечай по-русски, кратко и по делу.",
        "",
        "===== RULES =====",
        (card.rules_prompt or spec.rules_prompt or "").strip(),
        "===== КОНЕЦ RULES =====",
        "",
        "Кнопки пользователя (готовые сценарии):",
    ]
    for action in actions:
        lines.append(f"- {action.label}: {action.prompt}")
    if spec.chat_commands:
        lines.append("")
        lines.append("Slash-команды:")
        for cmd in spec.chat_commands:
            lines.append(f"- {cmd.command}: {cmd.description}")
    return "\n".join(lines).strip()


_ODATA_PORUCHENIYA_HINT = (
    "[Интеграции] Поручения 1С — constructor_integrations, tool=onec.docflow_tasks (OData). "
    "Не используй COM и не используй shell/curl для 1С."
)


def with_integration_hint(text: str) -> str:
    body = (text or "").strip()
    if _ODATA_PORUCHENIYA_HINT in body:
        return body
    return f"{_ODATA_PORUCHENIYA_HINT}\n\n{body}"


def build_action_message(action_prompt: str, *, attachment_paths: list[str] | None = None) -> str:
    body = f"Выполни сценарий кнопки:\n{action_prompt.strip()}"
    block = format_attachments_block(attachment_paths or [])
    if block:
        return f"{body}{block}"
    return body


def build_user_message(text: str, *, attachment_paths: list[str] | None = None) -> str:
    body = (text or "").strip()
    block = format_attachments_block(attachment_paths or [])
    if block and body:
        return f"{body}{block}"
    if block:
        return block.strip()
    return body


def ui_spec_has_open_questions(spec: UiSpec) -> bool:
    return bool(spec.needs_clarification)
