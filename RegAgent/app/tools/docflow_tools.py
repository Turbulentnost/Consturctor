"""OData-инструмент Документ.ТД_Поручения (ERP erp_pm)."""

from __future__ import annotations

from app.services.docflow_odata import handle_docflow_tasks
from app.session_store import saved_fio
from app.tools.ported.ac.base import BaseTool
from app.tools.ported.ac.tooling import (
    ToolCallResult,
    ToolDefinition,
    ToolExecutionMode,
    ToolSideEffectLevel,
)


class DocflowTasksTool(BaseTool):
    """Список Документ.ТД_Поручения из ERP через OData."""

    def __init__(self) -> None:
        super().__init__(
            ToolDefinition(
                name="onec.docflow_tasks",
                title="Поручения ТД_Поручения",
                description=(
                    "Список Документ.ТД_Поручения из erp_pm (форма ОткрытьСписок). "
                    "Каждая строка табличной части — отдельное поручение. "
                    "Возвращает urgency_tier и color по СрокИсполнения. "
                    "mine_only=true фильтрует по ФИО из сессии."
                ),
                side_effect_level=ToolSideEffectLevel.READ,
                execution_mode=ToolExecutionMode.EXTERNAL_API,
                requires_human_approval=False,
                timeout_seconds=45,
                input_schema={
                    "type": "object",
                    "properties": {
                        "only_open": {
                            "type": "boolean",
                            "description": "Исключить статус Отменено (по умолчанию false)",
                        },
                        "mine_only": {
                            "type": "boolean",
                            "description": "Только строки, где ответственное лицо = ФИО сессии",
                        },
                        "include_done": {
                            "type": "boolean",
                            "description": "Включить выполненные (only_open=false)",
                        },
                        "date_from": {
                            "type": "string",
                            "description": "Начало периода по дате создания YYYY-MM-DD",
                        },
                        "date_to": {
                            "type": "string",
                            "description": "Конец периода по дате создания YYYY-MM-DD",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Максимум записей, не больше 200",
                        },
                    },
                },
                output_schema={"type": "object"},
            )
        )

    def execute(self, input_data: dict) -> ToolCallResult:
        try:
            result = handle_docflow_tasks(input_data, actor_fio=saved_fio())
            return ToolCallResult(
                ok=True,
                tool_name=self.definition.name,
                output_data=result,
            )
        except Exception as exc:
            return ToolCallResult(
                ok=False,
                tool_name=self.definition.name,
                error_type="DOCFLOW_ERROR",
                error_message=str(exc),
            )
