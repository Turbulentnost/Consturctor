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
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )

