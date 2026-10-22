from __future__ import annotations

# Локальные оверрайды по подстроке ФИО (без учёта ь/ъ).
_POSITION_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("карташов", "Помощник Председателя совета директоров"),
    ("комарков", "Помощник Председателя совета директоров"),
    ("мангасарян", "Помощник Председателя совета директоров"),
    ("ильченко", "Помощник Председателя совета директоров"),
    ("тищенко марина николаевна", "Помощник Председателя совета директоров"),
)
_DEPARTMENT_OVERRIDES: tuple[tuple[str, str], ...] = (
    ("карташов", "Управление делами"),
    ("комарков", "Управление делами"),
    ("мангасарян", "Управление делами"),
)


def normalize_fio_key(value: str) -> str:
    text = (value or "").casefold()
    for ch in ("ь", "ъ", "\u0301"):
        text = text.replace(ch, "")
    return text


def lookup_profile_overrides(fio: str) -> tuple[str | None, str | None]:
    key = normalize_fio_key(fio)
    department: str | None = None
    position: str | None = None
    for needle, override in _DEPARTMENT_OVERRIDES:
        if normalize_fio_key(needle) in key:
            department = override
            break
    for needle, override in _POSITION_OVERRIDES:
        if normalize_fio_key(needle) in key:
            position = override
            break
    if position is None and all(part in key for part in ("тищенко", "марина", "николаевна")):
        position = "Помощник Председателя совета директоров"
    return department, position


def apply_profile_overrides(fio: str, department: str, position: str) -> tuple[str, str]:
    forced_department, forced_position = lookup_profile_overrides(fio)
    return forced_department or department or "", forced_position or position or ""
