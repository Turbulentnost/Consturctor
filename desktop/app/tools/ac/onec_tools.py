"""1C read-only tools, делегирующие выполнение worker-слою."""

from __future__ import annotations

from uuid import uuid4

from app.tools.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)
from app.tools.ac.base import BaseTool
from app.tools.ac.registry import ToolRegistry
from app.tools.ac.workers.base import BaseWorker
from app.tools.ac.workers.models import WorkerTask
from app.tools.ac.workers.onec_com32_helper import com32_worker_timeout_seconds

ONEC_COM32_RUNTIME = "com32"
ONEC_COM32_TIMEOUT_SECONDS = com32_worker_timeout_seconds()
ONEC_COM32_TOOLS = frozenset(
    {
        "onec.search_documents",
        "onec.get_document_card",
        "onec.search_tasks",
        "onec.get_task_card",
        "onec.meeting_service_notes",
    }
)


class OneCReadOnlyTool(BaseTool):
    """Базовый read-only инструмент 1С через worker."""

    def __init__(self, definition: ToolDefinition, worker: BaseWorker) -> None:
        """Сохранить definition и worker."""
        super().__init__(definition)
        self._worker = worker

    def execute(self, input_data: dict) -> ToolCallResult:
        """Вызвать 1C worker и вернуть ToolCallResult."""
        task = WorkerTask(
            task_id=str(uuid4()),
            tool_name=self.definition.name,
            input_data=input_data,
            timeout_seconds=self.definition.timeout_seconds,
        )
        try:
            worker_result = self._worker.execute(task)
        except Exception as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="WORKER_EXECUTION_ERROR",
                error_message=str(exc),
            )

        if worker_result.ok:
            return ToolCallResult(
                ok=True,
                tool_name=self.definition.name,
                output_data=worker_result.output_data or {},
            )
        return ToolCallResult(
            ok=False,
            tool_name=self.definition.name,
            error_type=worker_result.error_type,
            error_message=worker_result.error_message,
        )


class OneCSearchDocumentsTool(OneCReadOnlyTool):
    """Поиск документов в 1С."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент."""
        super().__init__(
            _definition("onec.search_documents", "Поиск документов 1С"),
            worker,
        )


class OneCGetDocumentCardTool(OneCReadOnlyTool):
    """Чтение карточки документа 1С."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент."""
        super().__init__(
            _definition("onec.get_document_card", "Чтение карточки документа 1С"),
            worker,
        )


class OneCSearchTasksTool(OneCReadOnlyTool):
    """Поиск задач и поручений в 1С."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент."""
        super().__init__(_definition("onec.search_tasks", "Поиск задач 1С"), worker)


class OneCGetTaskCardTool(OneCReadOnlyTool):
    """Чтение карточки задачи 1С."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент."""
        super().__init__(
            _definition("onec.get_task_card", "Чтение карточки задачи 1С"),
            worker,
        )


class OneCMeetingServiceNotesTool(OneCReadOnlyTool):
    """Чтение служебных записок на организацию совещаний. Только SELECT."""

    def __init__(self, worker: BaseWorker) -> None:
        super().__init__(
            ToolDefinition(
                name="onec.meeting_service_notes",
                title="Служебные записки на совещания",
                description=(
                    "Только чтение: служебные записки 1С с темой «организация совещаний». "
                    "Возвращает тему СЗ, тему совещания, место, желаемую дату/время, "
                    "длительность, руководителя, приоритет, периодичность, вид и признак ПСД. "
                    "date или date_from/date_to (YYYY-MM-DD). Ничего не записывает в 1С."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.COM_WORKER,
                requires_human_approval=False,
                timeout_seconds=ONEC_COM32_TIMEOUT_SECONDS,
                runtime=ONEC_COM32_RUNTIME,
                input_schema={
                    "type": "object",
                    "properties": {
                        "date": {"type": "string", "description": "Один день YYYY-MM-DD"},
                        "date_from": {"type": "string", "description": "Начало периода YYYY-MM-DD"},
                        "date_to": {"type": "string", "description": "Конец периода YYYY-MM-DD"},
                        "fio": {
                            "type": "string",
                            "description": "Кому направлены. Пусто — пользователь COM-сессии",
                        },
                        "max_results": {"type": "integer", "description": "Максимум записок, не больше 200"},
                    },
                },
                output_schema={"type": "object"},
            ),
            worker,
        )


def register_onec_readonly_tools(
    registry: ToolRegistry,
    worker: BaseWorker,
    *,
    skip_existing: bool = False,
) -> None:
    """Зарегистрировать read-only инструменты 1С."""
    for tool in [
        OneCSearchDocumentsTool(worker),
        OneCGetDocumentCardTool(worker),
        OneCSearchTasksTool(worker),
        OneCGetTaskCardTool(worker),
        OneCMeetingServiceNotesTool(worker),
    ]:
        if skip_existing and registry.has_tool(tool.definition.name):
            continue
        registry.register(tool)


def _definition(name: str, title: str) -> ToolDefinition:
    """Создать единый ToolDefinition для read-only 1С tool."""
    return ToolDefinition(
        name=name,
        title=title,
        description=f"{title} в read-only режиме.",
        side_effect_level=ToolSideEffectLevel.READ,
        execution_mode=ToolExecutionMode.COM_WORKER,
        requires_human_approval=False,
        timeout_seconds=ONEC_COM32_TIMEOUT_SECONDS,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        runtime=ONEC_COM32_RUNTIME,
    )

