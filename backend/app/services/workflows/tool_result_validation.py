"""Проверка ответа инструмента. Успешный вызов сам по себе ничего не доказывает.

Пять проверок: соответствие системы/сущности/операции, охват против запрошенного,
обязательные поля, завершённость пагинации, пригодность для следующего шага.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COMPLETE = "complete"
PARTIAL = "partial"
EMPTY_VALID = "empty_valid"
EMPTY_SUSPECT = "empty_suspect"
MISMATCH = "mismatch"

_ACCEPTED = {COMPLETE, EMPTY_VALID}

_COLLECTION_KEYS = (
    "rows",
    "items",
    "results",
    "messages",
    "tasks",
    "projects",
    "documents",
    "entities",
    "users",
    "files",
    "events",
    "value",
    "data",
    "tree",
    "records",
)
_COUNT_KEYS = ("count", "total", "total_count", "found", "matched")
_MORE_KEYS = ("truncated", "has_more", "more", "next_page", "next_cursor", "is_truncated")
_LIMIT_KEYS = ("limit", "top", "max_results", "max_items", "limit_per_person")


@dataclass
class ToolVerdict:
    data_status: str
    reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    next_action: str = ""

    @property
    def accepted(self) -> bool:
        return self.data_status in _ACCEPTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_status": self.data_status,
            "reasons": list(self.reasons),
            "checks": dict(self.checks),
            "next_action": self.next_action,
        }


def _as_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, list):
        return {"items": result}
    return {"value": result}


def _collection(payload: dict[str, Any]) -> tuple[str, list[Any]] | None:
    for key in _COLLECTION_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            return key, value
    for key, value in payload.items():
        if isinstance(value, list) and key not in {"warnings", "errors"}:
            return str(key), value
    return None


def _declared_count(payload: dict[str, Any]) -> int | None:
    for key in _COUNT_KEYS:
        value = payload.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value >= 0:
            return value
    return None


def _has_more(payload: dict[str, Any]) -> bool:
    for key in _MORE_KEYS:
        value = payload.get(key)
        if isinstance(value, bool) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return True
    return False


def _requested_limit(arguments: dict[str, Any]) -> int | None:
    for key in _LIMIT_KEYS:
        value = arguments.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
    return None


def _is_empty(payload: dict[str, Any]) -> bool:
    found = _collection(payload)
    if found is not None:
        return not found[1]
    meaningful = {
        key: value
        for key, value in payload.items()
        if key not in {"ok", "status", "source", "via", "warnings", "summary"}
        and value not in (None, "", [], {})
    }
    return not meaningful


def _missing_result_fields(payload: dict[str, Any], contract: dict[str, Any]) -> list[str]:
    expected = [str(f) for f in (contract.get("result_fields") or [])]
    if not expected:
        return []
    if any(field_name in payload for field_name in expected):
        return []
    return expected


def evaluate_tool_result(
    *,
    step: dict[str, Any] | None,
    name: str,
    arguments: dict[str, Any] | None,
    result: Any,
    next_step: dict[str, Any] | None = None,
    contract: dict[str, Any] | None = None,
) -> ToolVerdict:
    """Вердикт по одному вызову инструмента."""
    from app.services.local_mcp import tool_contracts

    step = step or {}
    arguments = arguments if isinstance(arguments, dict) else {}
    payload = _as_dict(result)
    contract = contract if contract is not None else (tool_contracts().get(name) or {})

    reasons: list[str] = []
    checks: dict[str, bool] = {}

    # 1. Система, сущность, операция.
    from app.services.workflow_tool_routing import normalize_operation

    mismatch: list[str] = []
    step_system = str(step.get("system") or "").strip().casefold()
    tool_system = str(contract.get("system") or "").strip().casefold()
    if step_system and tool_system and step_system != tool_system:
        mismatch.append(f"шагу нужна система {step_system}, а инструмент из {tool_system}")
    step_operation = normalize_operation(str(step.get("operation") or ""))
    tool_operation = str(contract.get("operation") or "").strip().casefold()
    if step_operation and tool_operation and step_operation != tool_operation:
        mismatch.append(f"шагу нужна операция {step_operation}, а инструмент делает {tool_operation}")
    candidates = [str(c) for c in (step.get("tool_candidates") or [])]
    if candidates and name and name not in candidates:
        mismatch.append(f"{name} не входит в кандидатов шага: {', '.join(candidates)}")
    checks["source"] = not mismatch
    reasons.extend(mismatch)

    error_text = ""
    if isinstance(payload.get("error"), str):
        error_text = payload["error"].strip()
    elif payload.get("ok") is False:
        error_text = str(payload.get("message") or "инструмент вернул ok=false")
    if error_text:
        return ToolVerdict(
            data_status=MISMATCH,
            reasons=[*reasons, f"ошибка инструмента: {error_text[:300]}"],
            checks={**checks, "source": False},
            next_action="Исправь параметры вызова или возьми другой инструмент из кандидатов шага.",
        )

    if mismatch:
        return ToolVerdict(
            data_status=MISMATCH,
            reasons=reasons,
            checks=checks,
            next_action="Возьми инструмент из кандидатов шага и повтори вызов.",
        )

    # 2. Охват против запрошенного.
    missing_params = [
        str(param)
        for param in (step.get("required_params") or [])
        if str(param) not in arguments or arguments.get(str(param)) in (None, "", [])
    ]
    checks["coverage"] = not missing_params
    if missing_params:
        reasons.append("в вызове нет параметров шага: " + ", ".join(missing_params))

    found = _collection(payload)
    items = found[1] if found else []
    empty = _is_empty(payload)
    if empty:
        if missing_params or not arguments:
            return ToolVerdict(
                data_status=EMPTY_SUSPECT,
                reasons=[*reasons, "пустой ответ при неполных параметрах вызова"],
                checks=checks,
                next_action=(
                    "Пусто — это не результат. Задай недостающие параметры "
                    "или выбери инструмент, который покрывает нужную сущность."
                ),
            )
        return ToolVerdict(
            data_status=EMPTY_VALID,
            reasons=[*reasons, "данных нет, но фильтры заданы корректно"],
            checks={**checks, "fields": True, "pagination": True, "next_step": True},
            next_action=str(step.get("on_empty") or ""),
        )

    # 3. Обязательные поля.
    missing_fields = _missing_result_fields(payload, contract)
    checks["fields"] = not missing_fields
    if missing_fields:
        reasons.append("в ответе нет ожидаемых полей: " + ", ".join(missing_fields))

    # 4. Пагинация.
    pagination_done = True
    declared = _declared_count(payload)
    if declared is not None and found is not None and declared > len(items):
        pagination_done = False
        reasons.append(f"получено {len(items)} из {declared} записей")
    if _has_more(payload):
        pagination_done = False
        reasons.append("источник сообщает, что есть ещё страницы")
    limit = _requested_limit(arguments)
    if limit and found is not None and len(items) >= limit:
        pagination_done = False
        reasons.append(f"ответ упёрся в limit={limit}, часть данных могла не попасть")
    checks["pagination"] = pagination_done

    # 5. Пригодность для следующего шага.
    next_ready = True
    if next_step:
        needed = [
            str(param)
            for param in (next_step.get("required_params") or [])
            if str(param) not in arguments
        ]
        if needed:
            sample = items[0] if items and isinstance(items[0], dict) else payload
            keys = {str(k).casefold() for k in (sample or {}).keys()}
            unresolved = [param for param in needed if param.casefold() not in keys]
            if unresolved and len(unresolved) == len(needed):
                next_ready = False
                reasons.append(
                    "для следующего шага не хватает данных: " + ", ".join(unresolved)
                )
    checks["next_step"] = next_ready

    if not (checks["coverage"] and checks["fields"] and pagination_done and next_ready):
        return ToolVerdict(
            data_status=PARTIAL,
            reasons=reasons,
            checks=checks,
            next_action=(
                "Данные неполные. Не делай выводов и не переходи к следующему шагу: "
                "уточни параметры, дочитай страницы или возьми более подходящий инструмент."
            ),
        )

    return ToolVerdict(data_status=COMPLETE, reasons=reasons, checks=checks)
