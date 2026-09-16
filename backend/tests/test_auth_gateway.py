import asyncio

from app.services import auth_service


def test_login_delegates_to_gateway_when_local_erp_down(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "auth_skip_erp_sql", False)
    monkeypatch.setattr(
        auth_service.settings,
        "auth_erp_gateway_url",
        "http://192.168.1.157:7812",
    )

    async def fake_reachable() -> bool:
        return False

    monkeypatch.setattr(auth_service, "_local_erp_reachable", fake_reachable)

    called: dict[str, str] = {}

    def fake_gateway(fio: str, password: str, client=auth_service.DEFAULT_CLIENT):
        called["fio"] = fio
        called["password"] = password
        return auth_service.LoginResponse(
            access_token="local-jwt",
            user=auth_service.UserOut(id="U1", fio=fio, department="D", position="P"),
        )

    monkeypatch.setattr(auth_service, "_login_via_erp_gateway", fake_gateway)

    def boom(*_args, **_kwargs):
        raise AssertionError("local erp_pm SQL must not run when gateway delegation is used")

    monkeypatch.setattr(auth_service, "find_user_by_fio", boom)

    result = asyncio.run(auth_service.login("Иванов Иван", "secret"))
    assert called["fio"] == "Иванов Иван"
    assert called["password"] == "secret"
    assert result.access_token == "local-jwt"
    assert result.user.fio == "Иванов Иван"


def test_erp_auth_unavailable_message_mentions_gateway():
    msg = auth_service._erp_auth_unavailable_message()
    assert "192.168.1.157" in msg or "BACKEND_URL" in msg
