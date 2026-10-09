"""Вкладка «Настройки»: переменные инструментов и пользователь агентов в Constructor."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError

from app import tool_settings
from app.config import settings
from app.platform.library import find_user
from app.tools.constructor_session import ConstructorSessionError, login

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"])


class EnvUpdate(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)
    reset: list[str] = Field(default_factory=list)


class UserUpdate(BaseModel):
    fio: str
    # Пусто — оставить сохранённый пароль.
    password: str = ""


@router.get("/env")
def get_env() -> dict[str, object]:
    tool_settings.ensure_applied()
    return tool_settings.snapshot()


@router.put("/env")
def put_env(body: EnvUpdate) -> dict[str, object]:
    blocked = {tool_settings.USER_FIO, tool_settings.USER_PASSWORD} & {*body.values, *body.reset}
    if blocked:
        raise HTTPException(status_code=400, detail="Пользователь агентов меняется отдельно")
    try:
        tool_settings.update(body.values, body.reset)
    except tool_settings.SettingsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return tool_settings.snapshot()


def _profile_file():
    return settings.platform_data_dir / "constructor_user.json"


def _cached_profile(fio: str) -> dict[str, object] | None:
    try:
        data = json.loads(_profile_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or str(data.get("fio") or "").casefold() != fio.casefold():
        return None
    return data


def _save_profile(profile: dict[str, object]) -> None:
    path = _profile_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8")


def _user_state() -> dict[str, object]:
    fio = settings.constructor_user_fio.strip()
    profile: dict[str, object] | None = None
    error = ""
    if fio:
        profile = _cached_profile(fio)
        if profile is None:
            try:
                found = find_user(fio)
            except SQLAlchemyError as exc:
                error = f"База Constructor недоступна: {type(exc).__name__}"
                found = None
            if found is not None:
                profile = {**found, "verified": False, "checked_at": ""}
    return {
        "fio": fio,
        "password_set": bool(settings.constructor_user_password),
        "profile": profile,
        "error": error,
    }


@router.get("/constructor-user")
def get_constructor_user() -> dict[str, object]:
    return _user_state()


@router.put("/constructor-user")
def put_constructor_user(body: UserUpdate) -> dict[str, object]:
    """Проверить вход в Constructor и только после этого сохранить ФИО и пароль."""
    fio = body.fio.strip()
    password = body.password or settings.constructor_user_password
    if not fio:
        raise HTTPException(status_code=400, detail="Укажите ФИО пользователя")
    if not password:
        raise HTTPException(status_code=400, detail="Укажите пароль")
    try:
        answer = login(fio, password)
    except ConstructorSessionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    user = answer.get("user") if isinstance(answer.get("user"), dict) else {}
    profile = {
        "fio": str(user.get("fio") or fio).strip(),
        "position": str(user.get("position") or "").strip(),
        "department": str(user.get("department") or "").strip(),
        "verified": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    changes = {tool_settings.USER_FIO: fio}
    if body.password:
        changes[tool_settings.USER_PASSWORD] = body.password
    tool_settings.update(changes, [])
    _save_profile(profile)
    logger.info("пользователь агентов: %s", fio)
    return _user_state()
