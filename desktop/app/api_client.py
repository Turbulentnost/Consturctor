from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx

from app.config import backend_url


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
    avatar_url: str | None = None


@dataclass(frozen=True, slots=True)
class HealthStatus:
    status: str
    erp_reachable: bool
    erp_server: str
    llm_provider: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    user: UserProfile


class ApiClient:
    def __init__(self, base_url: str | None = None, timeout: float = 20.0) -> None:
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

    def health(self) -> HealthStatus:
        data = self._request("GET", "/health")
        return HealthStatus(
            status=str(data.get("status", "")),
            erp_reachable=bool(data.get("erp_reachable")),
            erp_server=str(data.get("erp_server", "")),
            llm_provider=str(data.get("llm_provider", "")),
        )

    def search_users(self, search: str = "") -> list[str]:
        params = {"search": search} if search.strip() else None
        data = self._request("GET", "/api/v1/auth/users", params=params)
        items = data.get("items") or []
        return [str(x) for x in items]

    def login(self, fio: str, password: str) -> LoginResult:
        data = self._request(
            "POST",
            "/api/v1/auth/login",
            json={"fio": fio, "password": password},
        )
        user = self._parse_user(data.get("user") or {})
        token = str(data.get("access_token", ""))
        self._token = token
        return LoginResult(access_token=token, user=user)

    def me(self) -> UserProfile:
        data = self._request("GET", "/api/v1/auth/me")
        return self._parse_user(data)

    def fetch_bytes(self, path_or_url: str) -> bytes:
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            url = path_or_url
        else:
            url = f"{self.base_url}{path_or_url}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(url, headers=self._headers())
        except httpx.ConnectError as exc:
            raise ApiError(
                f"Не удалось подключиться к backend ({self.base_url})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время ожидания ответа backend") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return response.content

    def upload_avatar(self, file_path: str | Path) -> UserProfile:
        path = Path(file_path)
        if not path.is_file():
            raise ApiError("Файл не найден")
        url = f"{self.base_url}/api/v1/auth/me/avatar"
        mime = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
        }.get(path.suffix.lower(), "application/octet-stream")
        try:
            with httpx.Client(timeout=self._timeout) as client:
                with path.open("rb") as fh:
                    response = client.post(
                        url,
                        headers=self._headers(),
                        files={"file": (path.name, fh, mime)},
                    )
        except httpx.ConnectError as exc:
            raise ApiError(
                f"Не удалось подключиться к backend ({self.base_url})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время ожидания ответа backend") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return self._parse_user(response.json())

    @staticmethod
    def _parse_user(data: dict) -> UserProfile:
        avatar = data.get("avatar_url")
        return UserProfile(
            id=str(data.get("id", "")),
            fio=str(data.get("fio", "")),
            department=str(data.get("department", "")),
            avatar_url=str(avatar) if avatar else None,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.request(
                    method,
                    url,
                    json=json,
                    params=params,
                    headers=self._headers(),
                )
        except httpx.ConnectError as exc:
            raise ApiError(
                f"Не удалось подключиться к backend ({self.base_url})"
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError("Превышено время ожидания ответа backend") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc

        if response.status_code >= 400:
            detail = _extract_detail(response)
            raise ApiError(detail, status_code=response.status_code)

        if not response.content:
            return {}
        return response.json()


def _extract_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail
        if isinstance(detail, list) and detail:
            return str(detail[0])
    except Exception:
        pass
    if response.status_code == 401:
        return "Неверный логин или пароль"
    return f"Ошибка сервера ({response.status_code})"
