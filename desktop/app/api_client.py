from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class HealthStatus:
    status: str
    erp_reachable: bool
    erp_server: str
    llm_provider: str
    platform_services: tuple[tuple[str, bool, str], ...] = ()


@dataclass(frozen=True, slots=True)
class KpiSummary:
    total_runs: int
    success_rate: float
    error_rate: float
    hitl_rate: float
    operator_keep_rate: float | None
    tool_failure_rate: float


@dataclass(frozen=True, slots=True)
class RunStatus:
    run_id: str
    agent_id: str
    status: str
    tool_events_count: int


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
        services = []
        for item in data.get("platform_services") or []:
            services.append(
                (
                    str(item.get("name", "")),
                    bool(item.get("reachable")),
                    str(item.get("status", "")),
                )
            )
        return HealthStatus(
            status=str(data.get("status", "")),
            erp_reachable=bool(data.get("erp_reachable")),
            erp_server=str(data.get("erp_server", "")),
            llm_provider=str(data.get("llm_provider", "")),
            platform_services=tuple(services),
        )

    def kpi_summary(self) -> KpiSummary:
        data = self._request("GET", "/api/v1/kpi/summary")
        rate = data.get("operator_keep_rate")
        return KpiSummary(
            total_runs=int(data.get("total_runs") or 0),
            success_rate=float(data.get("success_rate") or 0.0),
            error_rate=float(data.get("error_rate") or 0.0),
            hitl_rate=float(data.get("hitl_rate") or 0.0),
            operator_keep_rate=float(rate) if rate is not None else None,
            tool_failure_rate=float(data.get("tool_failure_rate") or 0.0),
        )

    def start_run(self, agent_id: str, tools: list[str] | None = None) -> RunStatus:
        data = self._request(
            "POST",
            "/api/v1/runs",
            json={
                "agent_id": agent_id,
                "tools": tools or ["imap.list_unread"],
                "config": {},
            },
        )
        return RunStatus(
            run_id=str(data.get("run_id", "")),
            agent_id=str(data.get("agent_id", "")),
            status=str(data.get("status", "")),
            tool_events_count=int(data.get("tool_events_count") or 0),
        )

    def get_run(self, run_id: str) -> RunStatus:
        data = self._request("GET", f"/api/v1/runs/{run_id}")
        return RunStatus(
            run_id=str(data.get("run_id", "")),
            agent_id=str(data.get("agent_id", "")),
            status=str(data.get("status", "")),
            tool_events_count=int(data.get("tool_events_count") or 0),
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
        user_data = data.get("user") or {}
        user = UserProfile(
            id=str(user_data.get("id", "")),
            fio=str(user_data.get("fio", "")),
            department=str(user_data.get("department", "")),
        )
        token = str(data.get("access_token", ""))
        self._token = token
        return LoginResult(access_token=token, user=user)

    def me(self) -> UserProfile:
        data = self._request("GET", "/api/v1/auth/me")
        return UserProfile(
            id=str(data.get("id", "")),
            fio=str(data.get("fio", "")),
            department=str(data.get("department", "")),
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
