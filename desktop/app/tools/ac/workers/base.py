"""Базовый интерфейс worker-слоя для внешних интеграций."""

from abc import ABC, abstractmethod

from app.tools.ac.workers.models import WorkerResult, WorkerTask


class BaseWorker(ABC):
    """Универсальный интерфейс worker-а без зависимости от COM, UI или pywin32."""

    @abstractmethod
    def execute(self, task: WorkerTask) -> WorkerResult:
        """Выполнить задачу worker-а и вернуть структурированный результат."""
