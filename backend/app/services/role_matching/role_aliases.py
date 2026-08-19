"""Сопоставление должностей пользователя с ролями в типовых регламентах."""

from __future__ import annotations

import re

# (все подстроки в должности) → алиасы для поиска в тексте регламента
_POSITION_ALIASES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("помощник", "псд"),
        (
            "помощник псд",
            "секретар",
            "секретарь ревизионной комиссии",
            "pmo",
            "координатор pmo",
            "исполнит",
            "owner",
            "владелец",
            "action tracker",
            "decision log",
            "ревизион",
        ),
    ),
    (
        ("помощник", "председател"),
        (
            "помощник председателя совета директоров",
            "помощник псд",
            "председатель совета директоров",
            "совет директоров",
            "ceo",
            "pmo",
            "action tracker",
            "decision log",
            "поручен",
            "исполнит",
            "kpi",
            "операционн",
        ),
    ),
    (
        ("псд",),
        (
            "секретар",
            "pmo",
            "исполнит",
            "action tracker",
            "ревизион",
        ),
    ),
)


def _normalize(value: str) -> str:
    text = (value or "").casefold()
    for ch in ("ь", "ъ", "\u0301", "-", "–", "—"):
        text = text.replace(ch, "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def aliases_for_position(position: str, department: str = "") -> list[str]:
    key = _normalize(f"{position} {department}")
    seen: set[str] = set()
    out: list[str] = []
    for triggers, aliases in _POSITION_ALIASES:
        if not all(_normalize(trigger) in key for trigger in triggers):
            continue
        for alias in aliases:
            norm = _normalize(alias)
            if not norm or norm in seen:
                continue
            seen.add(norm)
            out.append(alias)
    return out
