"""Pydantic-модели протокола обмена задачами с worker-слоем."""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator, model_validator


class WorkerTask(BaseModel):
    """Задача, которую Tool/Runtime-слой передаёт worker-у для выполнения."""

    task_id: str
    tool_name: str
    input_data: dict
    timeout_seconds: int = Field(default=30, gt=0)

    @field_validator("task_id", "tool_name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value


class WorkerResult(BaseModel):
    """Структурированный результат выполнения задачи worker-ом."""

    task_id: str
    ok: bool
    output_data: dict | None = None
    error_type: str | None = None
    error_message: str | None = None

    @field_validator("task_id")
    @classmethod
    def validate_task_id(cls, value: str) -> str:
        """Проверить, что task_id заполнен."""
        if not value.strip():
            raise ValueError("task_id не должен быть пустым")
        return value

    @model_validator(mode="after")
    def validate_result_state(self) -> WorkerResult:
        """Проверить согласованность успешного и ошибочного результата."""
        if self.ok and self.output_data is None:
            self.output_data = {}

        if not self.ok and not self.error_type and not self.error_message:
            raise ValueError(
                "Если ok=False, должен быть указан error_type или error_message"
            )

        return self
