from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

import httpx

from app.config import (
    backend_url,
    regagent_test_fio,
    regagent_test_login_enabled,
    regagent_test_password,
    regagent_test_user_id,
)

LOCAL_TEST_TOKEN = "regagent-local-test-token"


class ApiError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class UserProfile:
    id: str
    fio: str
    department: str = ""
    position: str = ""
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    user: UserProfile


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or backend_url()).rstrip("/")
        self._timeout = timeout
        self._token: str | None = None

    @property
    def token(self) -> str | None:
        return self._token

    def set_token(self, token: str | None) -> None:
        self._token = token

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def search_users(self, search: str = "") -> list[str]:
        if regagent_test_login_enabled():
            fio = regagent_test_fio()
            if not fio:
                return []
            if search.strip() and _fio_key(search) not in _fio_key(fio):
                return []
            return [fio]
        params = {"search": search} if search.strip() else None
        data = self._request("GET", "/api/v1/auth/users", params=params)
        items = data.get("items") or []
        return [str(x) for x in items]

    def login(self, fio: str, password: str) -> LoginResult:
        if regagent_test_login_enabled() and _test_credentials_match(fio, password):
            try:
                return self._login_via_backend(fio, password)
            except ApiError:
                return self._local_test_login()
        return self._login_via_backend(fio, password)

    def me(self) -> UserProfile:
        if self._token == LOCAL_TEST_TOKEN:
            return self._local_test_user()
        data = self._request("GET", "/api/v1/auth/me")
        return self._parse_user(data)

    def _login_via_backend(self, fio: str, password: str) -> LoginResult:
        data = self._request(
            "POST",
            "/api/v1/auth/login",
            json={"fio": fio, "password": password},
        )
        user = self._parse_user(data.get("user") or {})
        token = str(data.get("access_token", ""))
        self._token = token
        return LoginResult(access_token=token, user=user)

    def _local_test_user(self) -> UserProfile:
        return UserProfile(
            id=regagent_test_user_id(),
            fio=regagent_test_fio(),
        )

    def _local_test_login(self) -> LoginResult:
        user = self._local_test_user()
        self._token = LOCAL_TEST_TOKEN
        return LoginResult(access_token=LOCAL_TEST_TOKEN, user=user)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
        timeout: float | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        last_connect: httpx.ConnectError | None = None
        response: httpx.Response | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=timeout or self._timeout) as client:
                    response = client.request(
                        method,
                        url,
                        json=json,
                        params=params,
                        headers=self._headers(),
                    )
                last_connect = None
                break
            except httpx.ConnectError as exc:
                last_connect = exc
                if attempt == 2:
                    raise ApiError(
                        f"Не удалось подключиться к backend ({self.base_url})"
                    ) from exc
                time.sleep(0.4 * (attempt + 1))
            except httpx.TimeoutException as exc:
                raise ApiError("Превышено время ожидания ответа backend") from exc
            except httpx.HTTPError as exc:
                raise ApiError(f"Ошибка сети: {exc}") from exc
        if last_connect is not None or response is None:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})")
        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _parse_user(data: dict) -> UserProfile:
        avatar = data.get("avatar_url")
        return UserProfile(
            id=str(data.get("id", "")),
            fio=str(data.get("fio", "")),
            department=str(data.get("department", "")),
            position=str(data.get("position", "")),
            avatar_url=str(avatar) if avatar else None,
        )


def _fio_key(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _test_credentials_match(fio: str, password: str) -> bool:
    expected_fio = regagent_test_fio()
    expected_password = regagent_test_password()
    if not expected_fio or not expected_password:
        return False
    return _fio_key(fio) == _fio_key(expected_fio) and password == expected_password


def _extract_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        if isinstance(detail, list) and detail:
            first = detail[0]
            if isinstance(first, dict):
                msg = first.get("msg") or first.get("message")
                if msg:
                    return str(msg)
            return str(first)
        if isinstance(detail, dict):
            msg = detail.get("msg") or detail.get("message")
            if msg:
                return str(msg)
    except Exception:
        body = response.text.strip()
        if body:
            return body
    if response.status_code == 401:
        return "Неверный логин или пароль"
    if response.status_code == 503:
        return "Сервис авторизации временно недоступен"
    return f"Ошибка backend (HTTP {response.status_code})"
