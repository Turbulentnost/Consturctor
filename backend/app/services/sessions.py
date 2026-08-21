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
_ONLINE_TTL_SEC = 90
_client = None
_client_failed = False

SESSION_REPLACED = "session_replaced"
SKIP_RUN_TITLE = "Пропущен плановый запуск"
SKIP_RUN_BODY = (
    "Пользователь не запускал приложение, поэтому система пропустила плановый запуск."
)


def new_session_id() -> str:
    return str(uuid.uuid4())


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
    client = _redis()
    if client is None:
        return
    key = _SESSION_KEY.format(user_id=user_id)
    client.set(key, session_id)
    client.delete(_ONLINE_KEY.format(user_id=user_id))


def current_session_id(user_id: str) -> str:
    client = _redis()
    if client is None:
        return ""
    return str(client.get(_SESSION_KEY.format(user_id=user_id)) or "")


def is_current_session(user_id: str, session_id: str) -> bool:
    if not session_id:
        return False
    current = current_session_id(user_id)
    if not current:
        return True
    return current == session_id


def mark_online(user_id: str, session_id: str) -> None:
    client = _redis()
    if client is None:
        return
    if not is_current_session(user_id, session_id):
        return
    client.set(_ONLINE_KEY.format(user_id=user_id), session_id, ex=_ONLINE_TTL_SEC)


def mark_offline(user_id: str, session_id: str = "") -> None:
    client = _redis()
    if client is None:
        return
    key = _ONLINE_KEY.format(user_id=user_id)
    if session_id:
        if str(client.get(key) or "") != session_id:
            return
    client.delete(key)


def is_user_online(user_id: str) -> bool:
    client = _redis()
    if client is None:
        return False
    return bool(client.get(_ONLINE_KEY.format(user_id=user_id)))
