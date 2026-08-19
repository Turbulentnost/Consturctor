from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings


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


def saved_backend_url() -> str:
    return str(_settings().value("server/backend_url", "", type=str) or "").strip()


def saved_auth_url() -> str:
    return str(_settings().value("server/auth_url", "", type=str) or "").strip()


def save_backend_url(url: str) -> None:
    s = _settings()
    s.setValue("server/backend_url", url.strip().rstrip("/"))
    s.sync()


def save_auth_url(url: str) -> None:
    s = _settings()
    s.setValue("server/auth_url", url.strip().rstrip("/"))
    s.sync()


def save_session(*, access_token: str, fio: str = "") -> None:
    s = _settings()
    s.setValue("session/remember", True)
    s.setValue("session/access_token", access_token)
    s.setValue("session/fio", fio.strip())
    s.sync()


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
