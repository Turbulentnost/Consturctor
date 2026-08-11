from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
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
    position: str = ""
    avatar_url: str | None = None
    can_change_department: bool = True
    department_change_available_at: datetime | None = None


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


@dataclass(frozen=True, slots=True)
class RegulationTable:
    headers: list[str]
    rows: list[list[str]]


@dataclass(frozen=True, slots=True)
class RegulationFragment:
    fragment_id: str
    page: int
    section: str
    kind: str
    text: str
    table: RegulationTable | None
    ocr_confidence: float
    section_path: list[str] | None = None
    block_type: str = "paragraph"
    table_headers: list[str] | None = None
    cells: dict[str, str] | None = None
    row_index: int | None = None


@dataclass(frozen=True, slots=True)
class RegulationParseResult:
    regulation_id: str
    file_name: str
    page_count: int
    table_count: int
    section_count: int
    recognition_quality: float
    is_scan: bool
    sections: list[str]
    fragments: list[RegulationFragment]


@dataclass(frozen=True, slots=True)
class MatchSignal:
    match_type: str
    confidence: float
    quote: str
    explanation: str


@dataclass(frozen=True, slots=True)
class RoleMatch:
    match_id: str
    fragment_id: str
    relation: str
    match_types: list[str]
    confidence: float
    model_confidence: float
    explanation: str
    requires_confirmation: bool
    status: str
    fragment: RegulationFragment
    signals: list[MatchSignal]


@dataclass(frozen=True, slots=True)
class RoleMatchResult:
    run_id: str
    regulation_id: str
    canonical_title: str
    department: str
    matches: list[RoleMatch]


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

    def upload_regulation(self, file_path: str | Path) -> RegulationParseResult:
        path = Path(file_path)
        if not path.is_file():
            raise ApiError("Файл не найден")
        url = f"{self.base_url}/api/v1/regulations/upload"
        mime = {
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".pdf": "application/pdf",
            ".md": "text/markdown",
            ".txt": "text/plain",
        }.get(path.suffix.lower(), "application/octet-stream")
        try:
            with httpx.Client(timeout=max(self._timeout, 240.0)) as client:
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
            raise ApiError("Превышено время распознавания регламента") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc

        if response.status_code >= 400:
            raise ApiError(_extract_detail(response), status_code=response.status_code)
        return self._parse_regulation(response.json())

    def get_regulation(self, regulation_id: str) -> RegulationParseResult:
        data = self._request("GET", f"/api/v1/regulations/{regulation_id}")
        return self._parse_regulation(data)

    def create_role_matches(
        self,
        regulation_id: str,
        *,
        position: str,
        department: str,
    ) -> RoleMatchResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/role-matches",
            json={"position": position.strip(), "department": department.strip()},
            timeout=max(self._timeout, 300.0),
        )
        return self._parse_role_matches(data)

    def decide_role_match(
        self,
        regulation_id: str,
        run_id: str,
        match_id: str,
        status: str,
    ) -> RoleMatchResult:
        data = self._request(
            "PATCH",
            f"/api/v1/regulations/{regulation_id}/role-matches/{run_id}/{match_id}",
            json={"status": status},
            timeout=max(self._timeout, 60.0),
        )
        return self._parse_role_matches(data)

    def list_departments(self) -> list[str]:
        data = self._request("GET", "/api/v1/auth/departments")
        items = data.get("items") or []
        return [str(x) for x in items]

    def update_department(self, department: str) -> UserProfile:
        data = self._request(
            "PATCH",
            "/api/v1/auth/me/department",
            json={"department": department},
        )
        return self._parse_user(data)

    @staticmethod
    def _parse_user(data: dict) -> UserProfile:
        avatar = data.get("avatar_url")
        available_raw = data.get("department_change_available_at")
        available_at: datetime | None = None
        if isinstance(available_raw, str) and available_raw.strip():
            try:
                available_at = datetime.fromisoformat(available_raw.replace("Z", "+00:00"))
            except ValueError:
                available_at = None
        return UserProfile(
            id=str(data.get("id", "")),
            fio=str(data.get("fio", "")),
            department=str(data.get("department", "")),
            position=str(data.get("position", "")),
            avatar_url=str(avatar) if avatar else None,
            can_change_department=bool(data.get("can_change_department", True)),
            department_change_available_at=available_at,
        )

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
        try:
            with httpx.Client(timeout=timeout or self._timeout) as client:
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

    @staticmethod
    def _parse_regulation(data: dict) -> RegulationParseResult:
        fragments: list[RegulationFragment] = []
        for item in data.get("fragments") or []:
            table_data = item.get("table") if isinstance(item, dict) else None
            table = None
            if isinstance(table_data, dict):
                table = RegulationTable(
                    headers=[str(x) for x in table_data.get("headers") or []],
                    rows=[
                        [str(cell) for cell in row]
                        for row in table_data.get("rows") or []
                        if isinstance(row, list)
                    ],
                )
            fragments.append(
                RegulationFragment(
                    fragment_id=str(item.get("fragmentId", "")),
                    page=int(item.get("page") or 1),
                    section=str(item.get("section") or ""),
                    kind=str(item.get("kind") or "text"),
                    text=str(item.get("text") or ""),
                    table=table,
                    ocr_confidence=float(item.get("ocrConfidence") or 0.0),
                    section_path=[str(x) for x in item.get("sectionPath") or []],
                    block_type=str(item.get("blockType") or "paragraph"),
                    table_headers=[str(x) for x in item.get("tableHeaders") or []],
                    cells={str(k): str(v) for k, v in (item.get("cells") or {}).items()},
                    row_index=int(item["rowIndex"]) if item.get("rowIndex") is not None else None,
                )
            )
        return RegulationParseResult(
            regulation_id=str(data.get("regulationId", "")),
            file_name=str(data.get("fileName", "")),
            page_count=int(data.get("pageCount") or 0),
            table_count=int(data.get("tableCount") or 0),
            section_count=int(data.get("sectionCount") or 0),
            recognition_quality=float(data.get("recognitionQuality") or 0.0),
            is_scan=bool(data.get("isScan")),
            sections=[str(x) for x in data.get("sections") or []],
            fragments=fragments,
        )

    @staticmethod
    def _parse_fragment(item: dict) -> RegulationFragment:
        table_data = item.get("table") if isinstance(item, dict) else None
        table = None
        if isinstance(table_data, dict):
            table = RegulationTable(
                headers=[str(x) for x in table_data.get("headers") or []],
                rows=[
                    [str(cell) for cell in row]
                    for row in table_data.get("rows") or []
                    if isinstance(row, list)
                ],
            )
        return RegulationFragment(
            fragment_id=str(item.get("fragmentId", "")),
            page=int(item.get("page") or 1),
            section=str(item.get("section") or ""),
            kind=str(item.get("kind") or "text"),
            text=str(item.get("text") or ""),
            table=table,
            ocr_confidence=float(item.get("ocrConfidence") or 0.0),
            section_path=[str(x) for x in item.get("sectionPath") or []],
            block_type=str(item.get("blockType") or "paragraph"),
            table_headers=[str(x) for x in item.get("tableHeaders") or []],
            cells={str(k): str(v) for k, v in (item.get("cells") or {}).items()},
            row_index=int(item["rowIndex"]) if item.get("rowIndex") is not None else None,
        )

    @staticmethod
    def _parse_role_matches(data: dict) -> RoleMatchResult:
        matches: list[RoleMatch] = []
        for item in data.get("matches") or []:
            fragment = ApiClient._parse_fragment(item.get("fragment") or {})
            signals = [
                MatchSignal(
                    match_type=str(signal.get("matchType") or ""),
                    confidence=float(signal.get("confidence") or 0.0),
                    quote=str(signal.get("quote") or ""),
                    explanation=str(signal.get("explanation") or ""),
                )
                for signal in item.get("signals") or []
                if isinstance(signal, dict)
            ]
            matches.append(
                RoleMatch(
                    match_id=str(item.get("matchId") or ""),
                    fragment_id=str(item.get("fragmentId") or ""),
                    relation=str(item.get("relation") or "none"),
                    match_types=[str(x) for x in item.get("matchTypes") or []],
                    confidence=float(item.get("confidence") or 0.0),
                    model_confidence=float(item.get("modelConfidence") or 0.0),
                    explanation=str(item.get("explanation") or ""),
                    requires_confirmation=bool(item.get("requiresUserConfirmation")),
                    status=str(item.get("status") or "pending"),
                    fragment=fragment,
                    signals=signals,
                )
            )
        profile = data.get("profile") or {}
        return RoleMatchResult(
            run_id=str(data.get("runId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            canonical_title=str(profile.get("canonicalTitle") or ""),
            department=str(profile.get("department") or ""),
            matches=matches,
        )


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
        pass
    if response.status_code == 401:
        return "Неверный логин или пароль"
    return f"Ошибка сервера ({response.status_code})"
