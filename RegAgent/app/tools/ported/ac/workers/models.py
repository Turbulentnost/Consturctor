"""Лёгкие модели протокола обмена задачами с worker-слоем."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Self


def _loads_object(payload: str) -> dict[str, Any]:
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Worker payload должен быть JSON-объектом")
    return data


@dataclass(slots=True)
class WorkerTask:
    """Задача, которую Tool/Runtime-слой передаёт worker-у для выполнения."""

    task_id: str
    tool_name: str
    input_data: dict[str, Any]
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("Поле не должно быть пустым")
        if not self.tool_name.strip():
            raise ValueError("Поле не должно быть пустым")
        if int(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds должен быть больше 0")
        if not isinstance(self.input_data, dict):
            raise ValueError("input_data должен быть JSON-объектом")
        self.timeout_seconds = int(self.timeout_seconds)

    @classmethod
    def model_validate_json(cls, payload: str) -> Self:
        data = _loads_object(payload)
        return cls(
            task_id=str(data.get("task_id") or ""),
            tool_name=str(data.get("tool_name") or ""),
            input_data=data.get("input_data") if isinstance(data.get("input_data"), dict) else {},
            timeout_seconds=int(data.get("timeout_seconds") or 30),
        )

    def model_dump_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True)


@dataclass(slots=True)
class WorkerResult:
    """Структурированный результат выполнения задачи worker-ом."""

    task_id: str
    ok: bool
    output_data: dict[str, Any] | None = field(default=None)
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id.strip():
            raise ValueError("task_id не должен быть пустым")
        if self.ok and self.output_data is None:
            self.output_data = {}
        if not self.ok and not self.error_type and not self.error_message:
            raise ValueError(
                "Если ok=False, должен быть указан error_type или error_message"
            )
        if self.output_data is not None and not isinstance(self.output_data, dict):
            raise ValueError("output_data должен быть JSON-объектом")

    @classmethod
    def model_validate_json(cls, payload: str) -> Self:
        data = _loads_object(payload)
        return cls(
            task_id=str(data.get("task_id") or ""),
            ok=bool(data.get("ok")),
            output_data=data.get("output_data") if isinstance(data.get("output_data"), dict) else None,
            error_type=(str(data.get("error_type")) if data.get("error_type") is not None else None),
            error_message=(str(data.get("error_message")) if data.get("error_message") is not None else None),
        )

    def model_dump_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=True)
