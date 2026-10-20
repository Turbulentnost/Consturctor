"""Конфигурации платформы: папки с полным циклом запуска ИИ-агента."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import settings

MANIFEST = "config.json"


PROMPT_SOURCES = ("instruction",)


class ModelParam(BaseModel):
    id: str
    value: str


class PlatformConfig(BaseModel):
    id: str
    title: str
    description: str = ""
    model: str = ""
    # Параметры варианта модели SDK: для grok-4.7 это reasoning_effort, fast и context.
    model_params: list[ModelParam] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    # Команда запуска относительно папки конфигурации, например ["node", "runner.mjs"].
    entry: list[str] = Field(default_factory=list)
    # Что уходит промптом при запуске опубликованного агента Constructor.
    prompt_source: str = "instruction"
    # Раннер принимает фотографии и файлы к сообщению.
    attachments: bool = False
    # Свой агент сначала планирует в режиме plan: план становится его инструкцией,
    # а каждый следующий запуск получает план и историю прошлого прогона.
    plan_instruction: bool = False
    path: str
    error: str = ""

    @property
    def runnable(self) -> bool:
        return bool(self.entry) and not self.error

    def public(self) -> dict[str, object]:
        return {**self.model_dump(), "runnable": self.runnable}


def configs_root() -> Path:
    return Path(settings.platform_configs_dir)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _model_params(value: object) -> tuple[list[ModelParam], str]:
    if value is None:
        return [], ""
    if not isinstance(value, list):
        return [], f"{MANIFEST}: model_params — список объектов id и value"
    params: list[ModelParam] = []
    for item in value:
        if not isinstance(item, dict):
            return [], f"{MANIFEST}: model_params — список объектов id и value"
        ident = _text(item.get("id"))
        raw = _text(item.get("value"))
        if not ident or not raw:
            return [], f"{MANIFEST}: у параметра модели нужны id и value"
        params.append(ModelParam(id=ident, value=raw))
    return params, ""


def _load(folder: Path) -> PlatformConfig:
    base = PlatformConfig(id=folder.name, title=folder.name, path=str(folder))
    try:
        data = json.loads((folder / MANIFEST).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return base.model_copy(update={"error": f"{MANIFEST}: {exc}"})
    if not isinstance(data, dict):
        return base.model_copy(update={"error": f"{MANIFEST}: ожидается объект"})
    tags = data.get("tags")
    entry = data.get("entry")
    error = ""
    if entry is not None and not (
        isinstance(entry, list) and entry and all(isinstance(part, str) and part.strip() for part in entry)
    ):
        error = f"{MANIFEST}: entry — непустой список строк"
        entry = []
    prompt_source = _text(data.get("prompt_source")) or "instruction"
    if prompt_source not in PROMPT_SOURCES:
        error = error or f"{MANIFEST}: prompt_source — одно из {', '.join(PROMPT_SOURCES)}"
    model_params, params_error = _model_params(data.get("model_params"))
    error = error or params_error
    return base.model_copy(
        update={
            "title": _text(data.get("title")) or folder.name,
            "description": _text(data.get("description")),
            "model": _text(data.get("model")),
            "model_params": model_params,
            "tags": [t.strip() for t in tags if isinstance(t, str) and t.strip()]
            if isinstance(tags, list)
            else [],
            "entry": [part.strip() for part in entry] if isinstance(entry, list) else [],
            "prompt_source": prompt_source,
            "attachments": data.get("attachments") is True,
            "plan_instruction": data.get("plan_instruction") is True,
            "error": error,
        }
    )


def list_configs() -> list[PlatformConfig]:
    root = configs_root()
    if not root.is_dir():
        return []
    folders = sorted(
        (p for p in root.iterdir() if p.is_dir() and (p / MANIFEST).is_file()),
        key=lambda p: p.name.lower(),
    )
    return [_load(folder) for folder in folders]


def internal_root() -> Path:
    return Path(settings.platform_internal_dir)


def find_config(config_id: str) -> PlatformConfig | None:
    """Конфигурация по id; служебные (internal_root) в список не попадают, но находятся здесь."""
    for config in list_configs():
        if config.id == config_id:
            return config
    folder = internal_root() / config_id
    if config_id and folder.parent == internal_root() and (folder / MANIFEST).is_file():
        return _load(folder)
    return None
