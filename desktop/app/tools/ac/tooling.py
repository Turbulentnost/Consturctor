"""Pydantic-модели для описания и результатов вызова инструментов агента."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class ToolSideEffectLevel(StrEnum):
    """Уровень воздействия инструмента на внешние данные."""

    READ = "read"
    CREATE_DRAFT = "create_draft"
    WRITE = "write"
    DANGEROUS = "dangerous"


class ToolExecutionMode(StrEnum):
    """Технический режим исполнения инструмента."""

    LOCAL = "local"
    COM_WORKER = "com_worker"
    BROWSER_WORKER = "browser_worker"
    EXTERNAL_API = "external_api"
    LLM = "llm"


class ToolDefinition(BaseModel):
    """Паспорт инструмента: описание, риск, схемы данных и параметры исполнения.

    Для `write`-инструментов `requires_human_approval=True` желательно, но не
    запрещается на уровне модели: окончательно ужесточать это правило будет
    будущий ToolGateway с учетом AgentSpec и политики запуска.
    """

    name: str
    title: str
    description: str
    side_effect_level: ToolSideEffectLevel
    execution_mode: ToolExecutionMode
    requires_human_approval: bool
    timeout_seconds: int = Field(default=30, gt=0)
    max_retries: int = Field(default=2, ge=0)
    input_schema: dict
    output_schema: dict

    @field_validator("name", "title", "description")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value

    @model_validator(mode="after")
    def validate_dangerous_requires_approval(self) -> ToolDefinition:
        """Проверить, что dangerous-инструмент требует HumanApproval."""
        if (
            self.side_effect_level == ToolSideEffectLevel.DANGEROUS
            and not self.requires_human_approval
        ):
            raise ValueError(
                "Если side_effect_level == dangerous, "
                "requires_human_approval должен быть True"
            )
        return self


class ToolCallRequest(BaseModel):
    """Запрос Runtime на вызов инструмента через будущий ToolGateway."""

    run_id: str
    tool_name: str
    input_data: dict

    @field_validator("run_id", "tool_name")
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        """Проверить, что обязательное текстовое поле заполнено."""
        if not value.strip():
            raise ValueError("Поле не должно быть пустым")
        return value


class ToolCallResult(BaseModel):
    """Результат вызова инструмента для Runtime, UI, Storage и Audit Log."""

    ok: bool
    tool_name: str
    output_data: dict | None = None
    error_type: str | None = None
    error_message: str | None = None
    requires_human_approval: bool = False

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        """Проверить, что имя инструмента заполнено."""
        if not value.strip():
            raise ValueError("tool_name не должен быть пустым")
        return value

    @model_validator(mode="after")
    def validate_result_state(self) -> ToolCallResult:
        """Проверить согласованность успешного, ошибочного и approval-результата."""
        if self.ok and self.output_data is None:
            self.output_data = {}

        if not self.ok and not self.error_type and not self.error_message:
            raise ValueError(
                "Если ok=False, должен быть указан error_type или error_message"
            )

        if self.requires_human_approval and self.ok:
            raise ValueError("Если requires_human_approval=True, ok должен быть False")

        return self
