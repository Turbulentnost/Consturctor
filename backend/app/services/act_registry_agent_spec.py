"""Спецификация агента ACT-реестра — регламент в ACT_REGISTRY.md (корень репо)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

_REPO_ROOT = Path(__file__).resolve().parents[3]
REGULATION_PATH = _REPO_ROOT / "ACT_REGISTRY.md"


def load_regulation_text() -> str:
    if REGULATION_PATH.is_file():
        return REGULATION_PATH.read_text(encoding="utf-8")
    return _FALLBACK_REGULATION


_FALLBACK_REGULATION = "# ACT-реестр\n\nФайл ACT_REGISTRY.md не найден в корне репозитория.\n"

DEFAULT_TASK = (
    "Выгрузи реестр поручений ACT (Document_ТД_Поручения) из 1С через OData: "
    "каждая строка Excel — отдельная задача (Мероприятие, Исполнитель, Срок, Статус). "
    "Сохрани act_porucheniya_*.xlsx на рабочий стол."
)

GOAL = (
    "ACT-реестр: OData Document_ТД_Поручения → Excel «Задачи ACT» на рабочем столе — "
    "одна строка на задачу; дополнение из протокола совещания (--- ПРОТОКОЛ ---). "
    "Чат: фильтры, построчные сводки, LLM-ответ. Регламент: ACT_REGISTRY.md."
)

CONSTRAINTS: list[str] = [
    "OData: Document_ТД_Поручения; ТЧ Поручения → Мероприятие, ОтветственноеЛицо_Key, СрокИсполнения.",
    "Excel: лист «Задачи ACT», колонки: Номер ACT | Задача | Исполнитель | Срок | Статус.",
    "Tools: onec.act_porucheniya_registry (backend), excel.create_workbook (DesktopHost :7830).",
    "Handler: act_porucheniya_registry — см. ACT_REGISTRY.md §3–7.",
    "Цвет строки (заметная пастель): «Принято» — зелёный; иначе по сроку задачи (просрочено / ≤3 / 4–7 / 8–14 / >14 дн.). "
    "Колонка «Статус» — как в 1С (В работе, Принято, Создано, Отменено), не метка критичности.",
    "Файл: act_porucheniya_{инициалы}_{workflow_id[:8]}.xlsx на Desktop.",
]

OUT_OF_SCOPE: list[str] = [
    "Запись и изменение карточек поручений в 1С (только чтение OData).",
    "Автоматическая правка ячеек Excel по чату — пользователь вносит правки в файл на рабочем столе.",
]

STEPS: list[dict[str, str]] = [
    {
        "id": "odata",
        "title": "OData + исполнители",
        "action": "Document_ТД_Поручения + Catalog_Пользователи/ФизическиеЛица",
        "done_when": "documents[].task_lines[] с executor, deadline",
    },
    {
        "id": "flatten",
        "title": "Плоские строки",
        "action": "flatten_documents_to_task_rows — 1 задача = 1 строка",
        "done_when": "N строк задач (не N документов)",
    },
    {
        "id": "filter",
        "title": "Фильтр из чата",
        "action": "parse_act_filter_from_task → apply_act_document_filters",
        "done_when": "Отфильтрованное подмножество task_lines",
    },
    {
        "id": "excel",
        "title": "Excel",
        "action": "excel.create_workbook через DesktopHost",
        "done_when": "desktop_path в tool_result",
    },
    {
        "id": "chat",
        "title": "Ответ LLM",
        "action": "compose_act_registry_answer + finalize_agent_answer",
        "done_when": "agent_message построчно по задачам",
    },
]

TEST_CRITERIA: list[str] = [
    "OData: ≥1 документ ACT; task_lines с исполнителями",
    "Excel: строк задач > строк документов (если есть многозадачные ACT)",
    "ACT00-00069 → 3 строки в Excel",
    "TESTS: PASS",
]

NOTES_HEADER = (
    "# ИИ-агент: ACT-реестр\n\n"
    "Полный регламент (tools, OData, поток, скрипты, TODO): **ACT_REGISTRY.md** в корне репозитория.\n"
)


def build_agent_route_dict() -> dict[str, Any]:
    return {
        "handler": "act_porucheniya_registry",
        "kind": "act_porucheniya",
        "mode": "",
        "default_task": DEFAULT_TASK,
        "source": "act_registry_spec",
        "version": 2,
        "tools": [
            "onec.act_porucheniya_registry",
            "act_protocol_merge",
            "excel.create_workbook",
        ],
    }


def build_plan_dict(*, document_excerpt: str = "") -> dict[str, Any]:
    regulation = load_regulation_text()
    raw = regulation
    if document_excerpt.strip() and document_excerpt.strip() not in regulation:
        raw += "\n\n## Доп. контекст\n" + document_excerpt.strip()[:4000]
    return {
        "title": "ACT-реестр: задачи Document_ТД_Поручения",
        "goal": GOAL,
        "constraints": list(CONSTRAINTS),
        "out_of_scope": list(OUT_OF_SCOPE),
        "steps": STEPS,
        "test_criteria": list(TEST_CRITERIA),
        "raw_text": raw,
        "runtime": {
            "kind": "act_porucheniya",
            "handler": "act_porucheniya_registry",
            "default_task": DEFAULT_TASK,
            "autonomy_level": 1,
            "regulation_path": "ACT_REGISTRY.md",
        },
        "agent_route": build_agent_route_dict(),
    }


def build_workflow_import_payload(
    *,
    workflow_id: str | None = None,
    document_text: str = "",
    document_name: str = "ACT_REGISTRY.md",
) -> dict[str, Any]:
    """Снимок для POST /api/v1/workflows/import (phase=done)."""
    wid = workflow_id or str(uuid4())
    regulation = document_text.strip() or load_regulation_text()
    plan = build_plan_dict()
    route = build_agent_route_dict()
    return {
        "id": wid,
        "title": "ИИ-агент: ACT-реестр поручений",
        "phase": "done",
        "notes": NOTES_HEADER + "\n" + regulation[:8000],
        "document_name": document_name,
        "document_text": regulation,
        "plan": plan,
        "attachments": [],
        "local_run": {
            "status": "published",
            "published": True,
            "can_publish": False,
            "tests_status": "pass",
            "execution_backend": "mcp",
            "runtime": {
                "kind": "act_porucheniya",
                "handler": "act_porucheniya_registry",
                "regulation_path": "ACT_REGISTRY.md",
            },
            "ui_mode": "chat",
            "passport_title": "ACT-реестр поручений",
            "seed": "act_porucheniya",
            "agent_route": route,
            "tools": route["tools"],
        },
        "plan_agent_id": "",
        "plan_run_id": "",
        "exec_agent_id": "mcp:act_porucheniya_registry",
        "exec_run_id": "",
        "last_result": "TESTS: PASS\nACT registry agent ready. See ACT_REGISTRY.md",
        "branch": "",
        "pr_url": "",
        "agent_route": route,
    }
