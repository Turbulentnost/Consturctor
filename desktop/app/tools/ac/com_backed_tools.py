"""COM-backed инструменты, работающие только через worker-протокол."""

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


class ComBackedTool(BaseTool):
    """Инструмент, делегирующий выполнение BaseWorker через WorkerTask."""

    def __init__(self, definition: ToolDefinition, worker: BaseWorker) -> None:
        """Сохранить описание инструмента и worker."""
        super().__init__(definition)
        self._worker = worker

    def execute(self, input_data: dict) -> ToolCallResult:
        """Создать WorkerTask, вызвать worker и вернуть ToolCallResult."""
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


class OutlookSearchMailComTool(ComBackedTool):
    """COM-backed инструмент поиска писем Outlook через worker."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент поиска писем Outlook."""
        super().__init__(
            ToolDefinition(
                name="outlook.search_mail",
                title="Поиск писем Outlook",
                description="Ищет письма Outlook через COM Worker.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.COM_WORKER,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
            worker,
        )


class OutlookReadCalendarComTool(ComBackedTool):
    """COM-backed инструмент чтения календаря Outlook через worker."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент чтения календаря Outlook."""
        super().__init__(
            ToolDefinition(
                name="outlook.read_calendar",
                title="Чтение календаря Outlook",
                description="Читает события календаря Outlook через COM Worker.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.COM_WORKER,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
            worker,
        )


class OutlookReadTasksComTool(ComBackedTool):
    """COM-backed инструмент чтения задач Outlook через worker."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент чтения задач Outlook."""
        super().__init__(
            ToolDefinition(
                name="outlook.read_tasks",
                title="Чтение задач Outlook",
                description="Читает задачи Outlook через COM Worker.",
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.COM_WORKER,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
            worker,
        )


class EmailCreateDraftComTool(ComBackedTool):
    """COM-backed инструмент создания черновика письма через worker."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент создания черновика письма."""
        super().__init__(
            ToolDefinition(
                name="email.create_draft",
                title="Создание черновика письма",
                description="Создаёт черновик письма Outlook через COM Worker.",
                side_effect_level=ToolSideEffectLevel.CREATE_DRAFT,
                execution_mode=ToolExecutionMode.COM_WORKER,
                requires_human_approval=False,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
            worker,
        )


class EmailSendComTool(ComBackedTool):
    """COM-backed dangerous-инструмент отправки письма через worker."""

    def __init__(self, worker: BaseWorker) -> None:
        """Создать инструмент отправки письма."""
        super().__init__(
            ToolDefinition(
                name="email.send",
                title="Отправка письма",
                description="Отправляет письмо через Outlook COM Worker. Опасное действие.",
                side_effect_level=ToolSideEffectLevel.DANGEROUS,
                execution_mode=ToolExecutionMode.COM_WORKER,
                requires_human_approval=True,
                input_schema={"type": "object"},
                output_schema={"type": "object"},
            ),
            worker,
        )


def register_outlook_com_tools(registry: ToolRegistry, worker: BaseWorker) -> None:
    """Зарегистрировать Outlook COM-backed инструменты в ToolRegistry."""
    registry.register(OutlookSearchMailComTool(worker))
    registry.register(OutlookReadCalendarComTool(worker))
    registry.register(OutlookReadTasksComTool(worker))
    registry.register(EmailCreateDraftComTool(worker))
    registry.register(EmailSendComTool(worker))
