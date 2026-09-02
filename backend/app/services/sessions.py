"""Active session per user and desktop app, plus presence for 'desktop online'.

State lives in Redis so API and Celery see the same picture.
Constructor and Orchestrator keep independent sessions: login in one app
does not close the other. A second login in the same app replaces that app.
"""

from __future__ import annotations

import logging
import uuid

from app.config import settings

logger = logging.getLogger(__name__)

CLIENTS = frozenset({"constructor", "orchestrator"})
DEFAULT_CLIENT = "constructor"

_SESSION_KEY = "constructor:session:{user_id}"
_SESSION_CLIENT_KEY = "constructor:session:{client}:{user_id}"
_ONLINE_KEY = "constructor:online:{user_id}"
_ONLINE_CLIENT_KEY = "constructor:online:{client}:{user_id}"
_ONLINE_TTL_SEC = 180
_PRESENT = "1"
_client = None
_client_failed = False

SESSION_REPLACED = "session_replaced"
SKIP_RUN_TITLE = "Пропущен плановый запуск"
SKIP_RUN_BODY = (
    "Оркестратор не был запущен, поэтому система пропустила плановый запуск."
)
RECONNECT_EVIDENCE = "ожидание подключения десктопа"
RECONNECT_RETRY_SEC = 45


def new_session_id() -> str:
    return str(uuid.uuid4())


def normalize_client(value: str | None) -> str:
    raw = (value or "").strip().casefold()
    if raw in CLIENTS:
        return raw
    return DEFAULT_CLIENT


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


def _session_key(user_id: str, client: str) -> str:
    return _SESSION_CLIENT_KEY.format(client=normalize_client(client), user_id=user_id)


def _legacy_session_key(user_id: str) -> str:
    return _SESSION_KEY.format(user_id=user_id)


def _online_key(user_id: str, client: str) -> str:
    return _ONLINE_CLIENT_KEY.format(client=normalize_client(client), user_id=user_id)


def _legacy_online_key(user_id: str) -> str:
    return _ONLINE_KEY.format(user_id=user_id)


def replace_session(user_id: str, session_id: str, client: str = DEFAULT_CLIENT) -> None:
    """Register the active session for one desktop app only."""
    client = normalize_client(client)
    redis_client = _redis()
    if redis_client is None:
        return
    try:
        redis_client.set(_session_key(user_id, client), session_id)
        redis_client.set(_online_key(user_id, client), session_id, ex=_ONLINE_TTL_SEC)
        # Legacy keys stay constructor-only so an old token without cid
        # is replaced by a new Constructor login, not by Orchestrator.
        if client == DEFAULT_CLIENT:
            redis_client.set(_legacy_session_key(user_id), session_id)
            redis_client.set(_legacy_online_key(user_id), session_id, ex=_ONLINE_TTL_SEC)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis replace_session failed user=%s client=%s: %s", user_id, client, exc)
        _reset_client()


def current_session_id(user_id: str, client: str = DEFAULT_CLIENT) -> str:
    redis_client = _redis()
    if redis_client is None:
        return ""
    client = normalize_client(client)
    try:
        value = str(redis_client.get(_session_key(user_id, client)) or "")
        if value:
            return value
        if client == DEFAULT_CLIENT:
            return str(redis_client.get(_legacy_session_key(user_id)) or "")
        return ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis current_session_id failed user=%s client=%s: %s", user_id, client, exc)
        _reset_client()
        return ""


def has_active_session(user_id: str, client: str = DEFAULT_CLIENT) -> bool:
    return bool(current_session_id(user_id, client))


def is_current_session(user_id: str, session_id: str, client: str = DEFAULT_CLIENT) -> bool:
    """True if this token may act for the user in this desktop app.

    Empty Redis session store for that app means locking is not active yet (allow).
    Empty sid is allowed only while the store is empty (legacy tokens).
    """
    current = current_session_id(user_id, client)
    if not current:
        return True
    if not session_id:
        return False
    return current == session_id


def mark_online(user_id: str, session_id: str = "", client: str = DEFAULT_CLIENT) -> None:
    redis_client = _redis()
    if redis_client is None:
        return
    client = normalize_client(client)
    if not is_current_session(user_id, session_id, client):
        return
    value = (session_id or "").strip() or _PRESENT
    try:
        redis_client.set(_online_key(user_id, client), value, ex=_ONLINE_TTL_SEC)
        if client == DEFAULT_CLIENT:
            redis_client.set(_legacy_online_key(user_id), value, ex=_ONLINE_TTL_SEC)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis mark_online failed user=%s client=%s: %s", user_id, client, exc)
        _reset_client()


def mark_offline(user_id: str, session_id: str = "", client: str = DEFAULT_CLIENT) -> None:
    redis_client = _redis()
    if redis_client is None:
        return
    client = normalize_client(client)
    keys = [_online_key(user_id, client)]
    if client == DEFAULT_CLIENT:
        keys.append(_legacy_online_key(user_id))
    try:
        for key in keys:
            if session_id:
                current = str(redis_client.get(key) or "")
                if current and current not in {session_id, _PRESENT}:
                    continue
            redis_client.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis mark_offline failed user=%s client=%s: %s", user_id, client, exc)
        _reset_client()


def presence_status(user_id: str, client: str = "") -> str:
    """online / offline / unknown. unknown means Redis is down, do not skip the slot.

    Without client: online if any desktop app of this user is present.
    With client: online only if that desktop app is present.
    """
    redis_client = _redis()
    if redis_client is None:
        return "unknown"
    try:
        wanted = normalize_client(client) if (client or "").strip() else ""
        if wanted:
            keys = [_online_key(user_id, wanted)]
            if wanted == DEFAULT_CLIENT:
                keys.append(_legacy_online_key(user_id))
        else:
            keys = [_legacy_online_key(user_id), *(_online_key(user_id, item) for item in sorted(CLIENTS))]
        if any(redis_client.get(key) for key in keys):
            return "online"
        return "offline"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis presence_status failed user=%s: %s", user_id, exc)
        _reset_client()
        return "unknown"


def is_user_online(user_id: str) -> bool:
    return presence_status(user_id) == "online"
