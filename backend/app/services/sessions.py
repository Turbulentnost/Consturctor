"""Единственная активная сессия пользователя и признак «десктоп онлайн».

Состояние в Redis, чтобы API и Celery worker видели одно и то же.
"""

from __future__ import annotations

import logging
import uuid

from app.config import settings

logger = logging.getLogger(__name__)

_SESSION_KEY = "constructor:session:{user_id}"
_ONLINE_KEY = "constructor:online:{user_id}"
_ONLINE_TTL_SEC = 180
_PRESENT = "1"
_client = None
_client_failed = False

SESSION_REPLACED = "session_replaced"
SKIP_RUN_TITLE = "Пропущен плановый запуск"
SKIP_RUN_BODY = (
    "Пользователь не запускал приложение, поэтому система пропустила плановый запуск."
)
RECONNECT_EVIDENCE = "ожидание подключения десктопа"
RECONNECT_RETRY_SEC = 45


def new_session_id() -> str:
    return str(uuid.uuid4())


def _reset_client() -> None:
    global _client, _client_failed
    _client = None
    _client_failed = False


def _redis():
    global _client, _client_failed
    if _client is not None:
        return _client
    try:
        import redis

        client = redis.Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.8,
            socket_timeout=0.8,
        )
        client.ping()
        _client = client
        _client_failed = False
        return client
    except Exception as exc:  # noqa: BLE001
        if not _client_failed:
            logger.warning("Redis session store unavailable: %s", exc)
        _client_failed = True
        return None


def replace_session(user_id: str, session_id: str) -> None:
    """Register the active session and keep presence alive across re-login."""
    client = _redis()
    if client is None:
        return
    key = _SESSION_KEY.format(user_id=user_id)
    online = _ONLINE_KEY.format(user_id=user_id)
    try:
        client.set(key, session_id)
        # Do not clear online: backend restarts / re-login used to drop presence and
        # Celery falsely skipped scheduled runs while the desktop was open.
        client.set(online, session_id, ex=_ONLINE_TTL_SEC)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis replace_session failed user=%s: %s", user_id, exc)
        _reset_client()


def current_session_id(user_id: str) -> str:
    client = _redis()
    if client is None:
        return ""
    try:
        return str(client.get(_SESSION_KEY.format(user_id=user_id)) or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis current_session_id failed user=%s: %s", user_id, exc)
        _reset_client()
        return ""


def has_active_session(user_id: str) -> bool:
    return bool(current_session_id(user_id))


def is_current_session(user_id: str, session_id: str) -> bool:
    """True if this token may act for the user.

    Empty Redis session store means locking is not active yet (allow).
    Empty sid is allowed only while the store is empty (legacy tokens).
    """
    current = current_session_id(user_id)
    if not current:
        return True
    if not session_id:
        return False
    return current == session_id


def mark_online(user_id: str, session_id: str = "") -> None:
    client = _redis()
    if client is None:
        return
    if not is_current_session(user_id, session_id):
        return
    value = (session_id or "").strip() or _PRESENT
    try:
        client.set(_ONLINE_KEY.format(user_id=user_id), value, ex=_ONLINE_TTL_SEC)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis mark_online failed user=%s: %s", user_id, exc)
        _reset_client()


def mark_offline(user_id: str, session_id: str = "") -> None:
    client = _redis()
    if client is None:
        return
    key = _ONLINE_KEY.format(user_id=user_id)
    try:
        if session_id:
            current = str(client.get(key) or "")
            if current and current not in {session_id, _PRESENT}:
                return
        client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis mark_offline failed user=%s: %s", user_id, exc)
        _reset_client()


def presence_status(user_id: str) -> str:
    """online / offline / unknown. unknown means Redis is down, do not skip the slot."""
    client = _redis()
    if client is None:
        return "unknown"
    try:
        if client.get(_ONLINE_KEY.format(user_id=user_id)):
            return "online"
        return "offline"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis presence_status failed user=%s: %s", user_id, exc)
        _reset_client()
        return "unknown"


def is_user_online(user_id: str) -> bool:
    return presence_status(user_id) == "online"
