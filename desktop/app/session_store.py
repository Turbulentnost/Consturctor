from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QSettings

logger = logging.getLogger(__name__)


def _trace(message: str) -> None:
    print(message, flush=True)
    logger.info(message)


def _settings() -> QSettings:
    return QSettings("turbobot", "desktop")


@dataclass(frozen=True, slots=True)
class StoredSession:
    access_token: str
    fio: str = ""
    remember: bool = False


def load_session() -> StoredSession | None:
    s = _settings()
    remember = bool(s.value("session/remember", False, type=bool))
    token = str(s.value("session/access_token", "", type=str) or "").strip()
    fio = str(s.value("session/fio", "", type=str) or "").strip()
    if not remember or not token:
        return None
    return StoredSession(access_token=token, fio=fio, remember=True)


def remember_preference() -> bool:
    return bool(_settings().value("session/remember", False, type=bool))


def saved_fio() -> str:
    return str(_settings().value("session/fio", "", type=str) or "").strip()


def save_session(*, access_token: str, fio: str = "") -> None:
    s = _settings()
    s.setValue("session/remember", True)
    s.setValue("session/access_token", access_token)
    s.setValue("session/fio", fio.strip())
    s.sync()
    _trace(f"Session saved fio={fio.strip() or '-'}")


def clear_session(*, keep_fio: bool = False) -> None:
    s = _settings()
    fio = saved_fio() if keep_fio else ""
    s.remove("session/access_token")
    s.setValue("session/remember", False)
    if keep_fio and fio:
        s.setValue("session/fio", fio)
    else:
        s.remove("session/fio")
    s.sync()
    _trace(f"Session cleared keep_fio={keep_fio} fio={fio or '-'}")
