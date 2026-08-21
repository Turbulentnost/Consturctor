"""Безопасный локальный Outlook COM worker."""

from app.tools.ported.ac.workers.base import BaseWorker
from app.tools.ported.ac.workers.models import WorkerResult, WorkerTask
from app.tools.ported.ac.workers.outlook_com_actions import (
    create_event,
    read_calendar,
    search_mail,
)
from app.tools.ported.ac.workers.outlook_diagnostics import (
    run_outlook_diagnostics,
)
from app.tools.ported.ac.workers.outlook_com_errors import (
    ComUnavailableError,
    DangerousOutlookActionBlockedError,
    OutlookAccessError,
    OutlookComError,
    UnsupportedOutlookToolError,
)

SEND_DISABLED_MESSAGE = (
    "Отправка писем через Outlook COM отключена в безопасном режиме"
)
DRAFT_DISABLED_MESSAGE = (
    "Создание черновиков через Outlook COM пока отключено в безопасном режиме"
)


class OutlookComWorker(BaseWorker):
    """Worker для безопасной работы с Outlook через COM в Windows-сессии пользователя."""

    def __init__(
        self,
        safe_mode: bool = True,
        allow_direct_com_calls: bool = False,
    ) -> None:
        """Создать Outlook worker; safe_mode запрещает все write/dangerous действия."""
        self.safe_mode = safe_mode
        self.allow_direct_com_calls = allow_direct_com_calls

    def execute(self, task: WorkerTask) -> WorkerResult:
        """Выполнить Outlook COM-задачу и всегда вернуть WorkerResult."""
        try:
            return self._execute_checked(task)
        except ComUnavailableError as exc:
            return self._error_result(task, "COM_NOT_AVAILABLE", str(exc))
        except DangerousOutlookActionBlockedError as exc:
            return self._error_result(task, "DANGEROUS_ACTION_BLOCKED", str(exc))
        except OutlookAccessError as exc:
            return self._error_result(task, "OUTLOOK_ACCESS_ERROR", str(exc))
        except UnsupportedOutlookToolError as exc:
            return self._error_result(
                task,
                "OUTLOOK_TOOL_NOT_IMPLEMENTED",
                str(exc),
            )
        except OutlookComError as exc:
            return self._error_result(task, "OUTLOOK_COM_ERROR", str(exc))
        except Exception as exc:
            return self._error_result(task, "OUTLOOK_WORKER_ERROR", str(exc))

    def _execute_checked(self, task: WorkerTask) -> WorkerResult:
        """Маршрутизировать разрешённые и заблокированные Outlook tool_name."""
        if task.tool_name == "outlook.diagnostics":
            if not self.allow_direct_com_calls:
                return self._direct_com_disabled_result(task)
            output_data = run_outlook_diagnostics(task.input_data)
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data=output_data,
            )

        if task.tool_name == "outlook.search_mail":
            if not self.allow_direct_com_calls:
                return self._direct_com_disabled_result(task)
            output_data = search_mail(task.input_data)
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data=output_data,
            )

        if task.tool_name == "outlook.read_calendar":
            if not self.allow_direct_com_calls:
                return self._direct_com_disabled_result(task)
            output_data = read_calendar(task.input_data)
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data=output_data,
            )

        if task.tool_name == "outlook.create_event":
            if not self.allow_direct_com_calls:
                return self._direct_com_disabled_result(task)
            output_data = create_event(task.input_data)
            return WorkerResult(
                task_id=task.task_id,
                ok=True,
                output_data=output_data,
            )

        if task.tool_name == "email.send":
            # TODO: Реальную отправку можно включать только после отдельной
            # политики HumanApproval и ручного тестирования.
            return self._error_result(
                task,
                "SEND_DISABLED_FOR_SAFETY",
                SEND_DISABLED_MESSAGE,
            )
        if task.tool_name == "email.create_draft":
            return self._error_result(
                task,
                "DRAFT_DISABLED_FOR_SAFETY",
                DRAFT_DISABLED_MESSAGE,
            )
        if task.tool_name.startswith(("outlook.", "email.")):
            return self._error_result(
                task,
                "OUTLOOK_TOOL_NOT_IMPLEMENTED",
                "Outlook COM tool пока не реализован или заблокирован safe_mode",
            )
        return self._error_result(
            task,
            "UNKNOWN_COM_TOOL",
            "Неизвестный COM tool_name",
        )

    def _direct_com_disabled_result(self, task: WorkerTask) -> WorkerResult:
        """Запретить реальные COM-вызовы вне subprocess worker-а."""
        return self._error_result(
            task,
            "DIRECT_COM_CALL_DISABLED",
            "Реальные Outlook COM-вызовы разрешены только через SubprocessComWorker",
        )

    def _error_result(
        self,
        task: WorkerTask,
        error_type: str,
        error_message: str,
    ) -> WorkerResult:
        """Вернуть структурированную ошибку worker-а."""
        return WorkerResult(
            task_id=task.task_id,
            ok=False,
            error_type=error_type,
            error_message=error_message,
        )
