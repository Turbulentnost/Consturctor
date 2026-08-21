"""Read-only worker для инструментов 1С."""

from __future__ import annotations

from collections.abc import Callable

from app.tools.ported.ac.workers.base import BaseWorker
from app.tools.ported.ac.workers.models import WorkerResult, WorkerTask
from app.tools.ported.ac.workers.onec_actions import (
    ensure_onec_readonly_input,
    ensure_onec_readonly_tool,
    get_document_card,
    get_task_card,
    list_meeting_service_notes,
    search_documents,
    search_tasks,
)
from app.tools.ported.ac.workers.onec_com_actions import execute_onec_com_readonly
from app.tools.ported.ac.workers.onec_errors import (
    OneCConnectionError,
    OneCDocumentNotFoundError,
    OneCQueryError,
    OneCReadOnlyPolicyError,
    UnsupportedOneCToolError,
)


class OneCReadOnlyWorker(BaseWorker):
    """Worker 1С, выполняющий только read-only операции."""

    _ACTIONS: dict[str, Callable[[dict], dict]] = {
        "onec.search_documents": search_documents,
        "onec.get_document_card": get_document_card,
        "onec.search_tasks": search_tasks,
        "onec.get_task_card": get_task_card,
        "onec.meeting_service_notes": list_meeting_service_notes,
    }

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Выполнить read-only задачу 1С и вернуть WorkerResult."""
        try:
            ensure_onec_readonly_tool(task.tool_name)
            ensure_onec_readonly_input(task.input_data)
            action = self._ACTIONS.get(task.tool_name)
            if action is None:
                raise UnsupportedOneCToolError(f"Неизвестный 1С tool: {task.tool_name}")
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data=action(task.input_data),
            )
        except OneCReadOnlyPolicyError as exc:
            return self._error(task, "ONEC_READONLY_POLICY_ERROR", exc)
        except OneCConnectionError as exc:
            return self._error(task, "ONEC_CONNECTION_ERROR", exc)
        except OneCDocumentNotFoundError as exc:
            return self._error(task, "ONEC_DOCUMENT_NOT_FOUND", exc)
        except OneCQueryError as exc:
            return self._error(task, "ONEC_QUERY_ERROR", exc)
        except UnsupportedOneCToolError as exc:
            return self._error(task, "UNKNOWN_ONEC_TOOL", exc)
        except Exception as exc:
            return self._error(task, "ONEC_WORKER_ERROR", exc)

    def _error(
        self,
        task: WorkerTask,
        error_type: str,
        exc: Exception,
    ) -> WorkerResult:
        """Вернуть структурированную ошибку 1С worker-а."""
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type=error_type,
            error_message=str(exc),
        )


class OneCApiWorker(OneCReadOnlyWorker):
    """Заготовка API worker-а 1С.

    Сейчас использует fake/read-only actions. Позже здесь появится HTTP/API
    реализация без изменения ToolGateway/Runtime.
    """


class OneCComWorker(BaseWorker):
    """Заготовка COMConnector worker-а 1С с read-only policy."""

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Делегировать будущему защищённому COMConnector слою."""
        return execute_onec_com_readonly(task)

