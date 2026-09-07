from app.core.jwt import create_access_token, validate_token
from app.services.sessions import (
    is_current_session,
    is_user_online,
    mark_offline,
    mark_online,
    presence_status,
    replace_session,
)


def test_token_carries_session_id() -> None:
    token = create_access_token(user_id="u-1", fio="Тест", session_id="sid-1")
    auth = validate_token(token)
    assert auth.user_id == "u-1"
    assert auth.session_id == "sid-1"
    assert auth.client == "constructor"


def test_token_carries_orchestrator_client() -> None:
    token = create_access_token(
        user_id="u-1",
        fio="Тест",
        session_id="sid-orch",
        client="orchestrator",
    )
    auth = validate_token(token)
    assert auth.session_id == "sid-orch"
    assert auth.client == "orchestrator"


def test_is_current_session_allows_when_store_empty() -> None:
    assert is_current_session("missing-user", "any-sid") is True


def test_is_current_session_allows_legacy_empty_sid_when_store_empty() -> None:
    assert is_current_session("missing-user", "") is True


def test_is_user_online_false_without_presence() -> None:
    assert is_user_online("nobody-online") is False
    assert presence_status("nobody-online") in {"offline", "unknown"}


def test_replace_session_invalidates_previous(monkeypatch) -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

        def ping(self):
            return True

    fake = FakeRedis()
    monkeypatch.setattr("app.services.sessions._redis", lambda: fake)
    monkeypatch.setattr("app.services.sessions._client", fake)
    replace_session("u-1", "sid-new")
    assert is_current_session("u-1", "sid-new") is True
    assert is_current_session("u-1", "sid-old") is False
    assert is_current_session("u-1", "") is False
    assert is_user_online("u-1") is True


def test_mark_online_works_with_legacy_empty_sid(monkeypatch) -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

        def ping(self):
            return True

    fake = FakeRedis()
    monkeypatch.setattr("app.services.sessions._redis", lambda: fake)
    monkeypatch.setattr("app.services.sessions._client", fake)
    mark_online("u-legacy", "")
    assert is_user_online("u-legacy") is True
    mark_offline("u-legacy", "")
    assert is_user_online("u-legacy") is False


def test_mark_online_refuses_stale_session(monkeypatch) -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

        def ping(self):
            return True

    fake = FakeRedis()
    monkeypatch.setattr("app.services.sessions._redis", lambda: fake)
    monkeypatch.setattr("app.services.sessions._client", fake)
    replace_session("u-1", "sid-new")
    assert is_user_online("u-1") is True
    mark_offline("u-1", "sid-new")
    assert is_user_online("u-1") is False
    mark_online("u-1", "sid-old")
    assert is_user_online("u-1") is False
    mark_online("u-1", "sid-new")
    assert is_user_online("u-1") is True


def test_constructor_login_does_not_replace_orchestrator_session(monkeypatch) -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

        def ping(self):
            return True

    fake = FakeRedis()
    monkeypatch.setattr("app.services.sessions._redis", lambda: fake)
    monkeypatch.setattr("app.services.sessions._client", fake)
    replace_session("u-1", "sid-orch", "orchestrator")
    replace_session("u-1", "sid-ctor", "constructor")
    assert is_current_session("u-1", "sid-ctor", "constructor") is True
    assert is_current_session("u-1", "sid-orch", "orchestrator") is True
    assert is_current_session("u-1", "sid-ctor", "orchestrator") is False
    replace_session("u-1", "sid-ctor-2", "constructor")
    assert is_current_session("u-1", "sid-ctor", "constructor") is False
    assert is_current_session("u-1", "sid-ctor-2", "constructor") is True
    assert is_current_session("u-1", "sid-orch", "orchestrator") is True


def test_orchestrator_login_does_not_replace_constructor_session(monkeypatch) -> None:
    store: dict[str, str] = {}

    class FakeRedis:
        def set(self, key, value, ex=None):
            store[key] = value

        def get(self, key):
            return store.get(key)

        def delete(self, key):
            store.pop(key, None)

        def ping(self):
            return True

    fake = FakeRedis()
    monkeypatch.setattr("app.services.sessions._redis", lambda: fake)
    monkeypatch.setattr("app.services.sessions._client", fake)
    replace_session("u-1", "sid-ctor", "constructor")
    replace_session("u-1", "sid-orch-2", "orchestrator")
    assert is_current_session("u-1", "sid-ctor", "constructor") is True
    assert is_current_session("u-1", "sid-orch-2", "orchestrator") is True
