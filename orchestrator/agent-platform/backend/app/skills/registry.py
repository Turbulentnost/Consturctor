"""Каталог skills стенда.

Реализации из Constructor сюда не переносятся.
Когда skill появится, его модуль вызывает register_skill() из catalog.load().
"""

from __future__ import annotations

from pydantic import BaseModel


class SkillSpec(BaseModel):
    id: str
    title: str
    description: str = ""


_SKILLS: list[SkillSpec] = []


def register_skill(spec: SkillSpec) -> None:
    if any(item.id == spec.id for item in _SKILLS):
        raise ValueError(f"skill already registered: {spec.id}")
    _SKILLS.append(spec)


def list_skills() -> list[SkillSpec]:
    return list(_SKILLS)


def load_catalog() -> None:
    from app.skills.catalog import load

    load()
