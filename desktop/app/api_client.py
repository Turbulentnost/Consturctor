from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from collections.abc import Callable

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
    bbox: list[float] | None = None
    location: dict | None = None
    style: str = ""
    content_hash: str = ""


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
class MatchEvidence:
    fragment_id: str
    quote: str


@dataclass(frozen=True, slots=True)
class ContextLinkedBlock:
    block_id: str
    relation: str
    text: str
    evidence: str
    confidence: float


@dataclass(frozen=True, slots=True)
class FunctionActor:
    text: str
    canonical_position: str
    source_block_id: str


@dataclass(frozen=True, slots=True)
class FunctionDependency:
    type: str
    block_id: str
    description: str


@dataclass(frozen=True, slots=True)
class RoleFunction:
    function_id: str
    target_block_id: str
    is_function: bool
    actor: FunctionActor
    action: str
    object: str
    recipient: str
    conditions: list[str]
    dependencies: list[FunctionDependency]
    evidence: list[MatchEvidence]
    proof_chain: list[ContextLinkedBlock]
    explanation: str
    confidence: float
    duplicate_group: str
    requires_confirmation: bool


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
    function: RoleFunction | None = None


@dataclass(frozen=True, slots=True)
class RoleMatchResult:
    run_id: str
    regulation_id: str
    canonical_title: str
    department: str
    matches: list[RoleMatch]
    functions: list[RoleFunction] | None = None
    audit: dict | None = None


@dataclass(frozen=True, slots=True)
class ReadinessQuestion:
    question_id: str
    function_id: str
    target_field: str
    severity: str
    question: str
    reason: str
    answer_type: str
    options: list[str]
    affected_blocks: list[str]
    answered: bool = False
    answer: str = ""


@dataclass(frozen=True, slots=True)
class ReadinessChange:
    change_id: str
    source: dict
    operation: str
    target_block_id: str
    before: str
    after: str
    reason: str
    affected_functions: list[str]
    affected_blocks: list[str]
    status: str


@dataclass(frozen=True, slots=True)
class AgentReadinessResult:
    readiness_run_id: str
    regulation_id: str
    role_match_run_id: str
    score: int
    blocking: list[str]
    important: list[str]
    optional: list[str]
    questions: list[ReadinessQuestion]
    changes: list[ReadinessChange]
    status: str


@dataclass(frozen=True, slots=True)
class RevisionDiffBlock:
    block_id: str
    section: str
    before: str
    after: str
    page: int
    bbox: list[float] | None
    status: str


@dataclass(frozen=True, slots=True)
class RevisionPreviewPage:
    page: int
    image_url: str


@dataclass(frozen=True, slots=True)
class RegulationRevisionResult:
    revision_id: str
    regulation_id: str
    readiness_run_id: str
    document_path: str
    protocol_path: str
    pdf_path: str
    source_preview_html: str
    revised_preview_html: str
    source_preview_pages: list[RevisionPreviewPage]
    revised_preview_pages: list[RevisionPreviewPage]
    diff_blocks: list[RevisionDiffBlock]
    download_url: str
    pdf_download_url: str
    protocol_url: str
    message: str


@dataclass(frozen=True, slots=True)
class AgentDraft:
    draft_id: str
    regulation_id: str
    role_match_run_id: str
    readiness_run_id: str
    title: str
    position: str
    department: str
    status: str
    progress: int
    readiness: AgentReadinessResult | None = None
    agent_suggestions: list[AgentSuggestion] | None = None
    updated_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class AgentSuggestion:
    agent_id: str
    title: str
    description: str
    regulation_id: str
    role_match_run_id: str
    function_id: str
    source_block_id: str


@dataclass(frozen=True, slots=True)
class RegulationCreationMessage:
    message_id: str
    draft_id: str
    role: str
    content: str
    structured: dict


@dataclass(frozen=True, slots=True)
class RegulationCreationSession:
    draft_id: str
    status: str
    cursor_agent_id: str
    latest_run_id: str
    positions: list[str]
    messages: list[RegulationCreationMessage]
    result_regulation: RegulationParseResult | None
    result_document_path: str


@dataclass(frozen=True, slots=True)
class QuestionChatMessage:
    message_id: str
    session_id: str
    role: str
    content: str
    structured: dict


@dataclass(frozen=True, slots=True)
class QuestionChatSession:
    session_id: str
    draft_id: str
    readiness_run_id: str
    question_id: str
    function_id: str
    target_field: str
    status: str
    context: dict
    messages: list[QuestionChatMessage]


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

    def start_regulation_creation(self) -> RegulationCreationSession:
        data = self._request(
            "POST",
            "/api/v1/regulation-creation/sessions",
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_creation_session(data)

    def send_regulation_creation_message(self, draft_id: str, message: str) -> RegulationCreationSession:
        data = self._request(
            "POST",
            f"/api/v1/regulation-creation/sessions/{draft_id}/messages",
            json={"message": message},
            timeout=max(self._timeout, 420.0),
        )
        return self._parse_creation_session(data)

    def stream_regulation_creation_message(
        self,
        draft_id: str,
        message: str,
        on_event: Callable[[str, str], None],
    ) -> RegulationCreationSession:
        url = f"{self.base_url}/api/v1/regulation-creation/sessions/{draft_id}/messages/stream"
        final_session: RegulationCreationSession | None = None
        try:
            with httpx.Client(timeout=None) as client:
                with client.stream(
                    "POST",
                    url,
                    headers={**self._headers(), "Accept": "text/event-stream"},
                    json={"message": message},
                ) as response:
                    if response.status_code >= 400:
                        body = response.read().decode("utf-8", errors="replace")
                        raise ApiError(body or "Ошибка создания регламента", status_code=response.status_code)
                    event_name = "message"
                    data_lines: list[str] = []
                    for line in response.iter_lines():
                        if line == "":
                            if data_lines:
                                payload = _parse_sse_payload("\n".join(data_lines))
                                payload_type = str(payload.get("type") or event_name)
                                if payload_type in {"thinking", "assistant"}:
                                    on_event(payload_type, str(payload.get("text") or ""))
                                elif payload_type == "error":
                                    raise ApiError(str(payload.get("message") or "Ошибка Cursor Agent"))
                                elif payload_type == "session" and isinstance(payload.get("session"), dict):
                                    final_session = self._parse_creation_session(payload["session"])
                            event_name = "message"
                            data_lines = []
                            continue
                        if line.startswith("event:"):
                            event_name = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].strip())
        except httpx.ConnectError as exc:
            raise ApiError(f"Не удалось подключиться к backend ({self.base_url})") from exc
        except httpx.HTTPError as exc:
            raise ApiError(f"Ошибка сети: {exc}") from exc
        if final_session is None:
            raise ApiError("Backend не вернул итоговую сессию создания регламента")
        return final_session

    def terminate_regulation_creation_sessions(self) -> None:
        if not self._token:
            return
        self._request(
            "POST",
            "/api/v1/regulation-creation/sessions/terminate-active",
            timeout=max(self._timeout, 30.0),
        )

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

    def create_readiness_run(self, regulation_id: str, role_match_run_id: str) -> AgentReadinessResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/role-matches/{role_match_run_id}/readiness",
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_readiness(data)

    def answer_readiness_question(
        self,
        regulation_id: str,
        readiness_run_id: str,
        question_id: str,
        answer: str,
    ) -> AgentReadinessResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/readiness/{readiness_run_id}/answers",
            json={"questionId": question_id, "answer": answer},
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_readiness(data)

    def update_readiness_change(
        self,
        regulation_id: str,
        readiness_run_id: str,
        change_id: str,
        status: str,
        after: str = "",
    ) -> AgentReadinessResult:
        data = self._request(
            "PATCH",
            f"/api/v1/regulations/{regulation_id}/readiness/{readiness_run_id}/changes/{change_id}",
            json={"status": status, "after": after},
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_readiness(data)

    def finalize_readiness(
        self,
        regulation_id: str,
        readiness_run_id: str,
    ) -> RegulationRevisionResult:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/readiness/{readiness_run_id}/finalize",
            timeout=max(self._timeout, 180.0),
        )
        return RegulationRevisionResult(
            revision_id=str(data.get("revisionId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            readiness_run_id=str(data.get("readinessRunId") or ""),
            document_path=str(data.get("documentPath") or ""),
            protocol_path=str(data.get("protocolPath") or ""),
            pdf_path=str(data.get("pdfPath") or ""),
            source_preview_html=str(data.get("sourcePreviewHtml") or ""),
            revised_preview_html=str(data.get("revisedPreviewHtml") or ""),
            source_preview_pages=[
                RevisionPreviewPage(
                    page=int(item.get("page") or 0),
                    image_url=str(item.get("imageUrl") or ""),
                )
                for item in data.get("sourcePreviewPages") or []
                if isinstance(item, dict)
            ],
            revised_preview_pages=[
                RevisionPreviewPage(
                    page=int(item.get("page") or 0),
                    image_url=str(item.get("imageUrl") or ""),
                )
                for item in data.get("revisedPreviewPages") or []
                if isinstance(item, dict)
            ],
            diff_blocks=[
                RevisionDiffBlock(
                    block_id=str(item.get("blockId") or ""),
                    section=str(item.get("section") or ""),
                    before=str(item.get("before") or ""),
                    after=str(item.get("after") or ""),
                    page=int(item.get("page") or 0),
                    bbox=[float(value) for value in item.get("bbox") or []]
                    if isinstance(item.get("bbox"), list)
                    else None,
                    status=str(item.get("status") or ""),
                )
                for item in data.get("diffBlocks") or []
                if isinstance(item, dict)
            ],
            download_url=str(data.get("downloadUrl") or ""),
            pdf_download_url=str(data.get("pdfDownloadUrl") or ""),
            protocol_url=str(data.get("protocolUrl") or ""),
            message=str(data.get("message") or ""),
        )

    def create_agent_draft(self, regulation_id: str, role_match_run_id: str) -> AgentDraft:
        data = self._request(
            "POST",
            f"/api/v1/regulations/{regulation_id}/role-matches/{role_match_run_id}/draft",
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_agent_draft(data)

    def list_agent_drafts(self) -> list[AgentDraft]:
        data = self._request("GET", "/api/v1/agents/drafts", timeout=max(self._timeout, 60.0))
        return [self._parse_agent_draft(item) for item in data.get("items") or [] if isinstance(item, dict)]

    def get_agent_draft(self, draft_id: str) -> AgentDraft:
        data = self._request("GET", f"/api/v1/agents/drafts/{draft_id}", timeout=max(self._timeout, 60.0))
        return self._parse_agent_draft(data)

    def delete_agent_draft(self, draft_id: str) -> None:
        self._request("DELETE", f"/api/v1/agents/drafts/{draft_id}", timeout=max(self._timeout, 60.0))

    def ensure_draft_readiness(self, draft_id: str) -> AgentDraft:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/readiness",
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_agent_draft(data)

    def update_agent_draft_status(self, draft_id: str, status: str) -> AgentDraft:
        data = self._request(
            "PATCH",
            f"/api/v1/agents/drafts/{draft_id}/status",
            json={"status": status},
            timeout=max(self._timeout, 60.0),
        )
        return self._parse_agent_draft(data)

    def reanalyze_revision_document(self, draft_id: str) -> list[AgentSuggestion]:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/reanalyze-revision",
            timeout=max(self._timeout, 420.0),
        )
        return [
            self._parse_agent_suggestion(item)
            for item in data.get("items") or []
            if isinstance(item, dict)
        ]

    @staticmethod
    def _parse_agent_suggestion(data: dict) -> AgentSuggestion:
        return AgentSuggestion(
            agent_id=str(data.get("agentId") or ""),
            title=str(data.get("title") or ""),
            description=str(data.get("description") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            role_match_run_id=str(data.get("roleMatchRunId") or ""),
            function_id=str(data.get("functionId") or ""),
            source_block_id=str(data.get("sourceBlockId") or ""),
        )

    def create_question_chat(self, draft_id: str, question_id: str) -> QuestionChatSession:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/questions/{question_id}/chat",
            timeout=max(self._timeout, 120.0),
        )
        return self._parse_question_chat(data)

    def latest_question_chat(self, draft_id: str) -> QuestionChatSession:
        data = self._request(
            "GET",
            f"/api/v1/agents/drafts/{draft_id}/chat/latest",
            timeout=max(self._timeout, 60.0),
        )
        return self._parse_question_chat(data)

    def send_question_chat_message(
        self,
        draft_id: str,
        question_id: str,
        message: str,
    ) -> QuestionChatSession:
        data = self._request(
            "POST",
            f"/api/v1/agents/drafts/{draft_id}/questions/{question_id}/chat/messages",
            json={"message": message},
            timeout=max(self._timeout, 180.0),
        )
        return self._parse_question_chat(data)

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
                    bbox=[float(x) for x in item.get("bbox") or []] or None,
                    location=item.get("location") if isinstance(item.get("location"), dict) else {},
                    style=str(item.get("style") or ""),
                    content_hash=str(item.get("contentHash") or ""),
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
    def _parse_creation_session(data: dict) -> RegulationCreationSession:
        result_raw = data.get("resultRegulation")
        return RegulationCreationSession(
            draft_id=str(data.get("draftId") or ""),
            status=str(data.get("status") or ""),
            cursor_agent_id=str(data.get("cursorAgentId") or ""),
            latest_run_id=str(data.get("latestRunId") or ""),
            positions=[str(item) for item in data.get("positions") or []],
            messages=[
                RegulationCreationMessage(
                    message_id=str(item.get("messageId") or ""),
                    draft_id=str(item.get("draftId") or ""),
                    role=str(item.get("role") or ""),
                    content=str(item.get("content") or ""),
                    structured=item.get("structured") if isinstance(item.get("structured"), dict) else {},
                )
                for item in data.get("messages") or []
                if isinstance(item, dict)
            ],
            result_regulation=ApiClient._parse_regulation(result_raw) if isinstance(result_raw, dict) else None,
            result_document_path=str(data.get("resultDocumentPath") or ""),
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
            bbox=[float(x) for x in item.get("bbox") or []] or None,
            location=item.get("location") if isinstance(item.get("location"), dict) else {},
            style=str(item.get("style") or ""),
            content_hash=str(item.get("contentHash") or ""),
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
            function = ApiClient._parse_role_function(item.get("function"))
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
                    function=function,
                )
            )
        profile = data.get("profile") or {}
        return RoleMatchResult(
            run_id=str(data.get("runId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            canonical_title=str(profile.get("canonicalTitle") or ""),
            department=str(profile.get("department") or ""),
            matches=matches,
            functions=[
                parsed
                for parsed in (ApiClient._parse_role_function(item) for item in data.get("functions") or [])
                if parsed is not None
            ],
            audit=data.get("audit") if isinstance(data.get("audit"), dict) else {},
        )

    @staticmethod
    def _parse_role_function(data: object) -> RoleFunction | None:
        if not isinstance(data, dict):
            return None
        actor_data = data.get("actor") if isinstance(data.get("actor"), dict) else {}
        actor = FunctionActor(
            text=str(actor_data.get("text") or ""),
            canonical_position=str(actor_data.get("canonicalPosition") or ""),
            source_block_id=str(actor_data.get("sourceBlockId") or ""),
        )
        dependencies = [
            FunctionDependency(
                type=str(item.get("type") or ""),
                block_id=str(item.get("blockId") or ""),
                description=str(item.get("description") or ""),
            )
            for item in data.get("dependencies") or []
            if isinstance(item, dict)
        ]
        evidence = [
            MatchEvidence(
                fragment_id=str(item.get("fragmentId") or item.get("blockId") or ""),
                quote=str(item.get("quote") or ""),
            )
            for item in data.get("evidence") or []
            if isinstance(item, dict)
        ]
        proof_chain = [
            ContextLinkedBlock(
                block_id=str(item.get("blockId") or ""),
                relation=str(item.get("relation") or ""),
                text=str(item.get("text") or ""),
                evidence=str(item.get("evidence") or ""),
                confidence=float(item.get("confidence") or 0.0),
            )
            for item in data.get("proofChain") or []
            if isinstance(item, dict)
        ]
        return RoleFunction(
            function_id=str(data.get("functionId") or ""),
            target_block_id=str(data.get("targetBlockId") or ""),
            is_function=bool(data.get("isFunction")),
            actor=actor,
            action=str(data.get("action") or ""),
            object=str(data.get("object") or ""),
            recipient=str(data.get("recipient") or ""),
            conditions=[str(x) for x in data.get("conditions") or []],
            dependencies=dependencies,
            evidence=evidence,
            proof_chain=proof_chain,
            explanation=str(data.get("explanation") or ""),
            confidence=float(data.get("confidence") or 0.0),
            duplicate_group=str(data.get("duplicateGroup") or ""),
            requires_confirmation=bool(data.get("requiresUserConfirmation")),
        )

    @staticmethod
    def _parse_readiness(data: dict) -> AgentReadinessResult:
        questions = [
            ReadinessQuestion(
                question_id=str(item.get("questionId") or ""),
                function_id=str(item.get("functionId") or ""),
                target_field=str(item.get("targetField") or ""),
                severity=str(item.get("severity") or ""),
                question=str(item.get("question") or ""),
                reason=str(item.get("reason") or ""),
                answer_type=str(item.get("answerType") or "text"),
                options=[str(x) for x in item.get("options") or []],
                affected_blocks=[str(x) for x in item.get("affectedBlocks") or []],
                answered=bool(item.get("answered")),
                answer=str(item.get("answer") or ""),
            )
            for item in data.get("questions") or []
            if isinstance(item, dict)
        ]
        changes = [
            ReadinessChange(
                change_id=str(item.get("changeId") or ""),
                source=item.get("source") if isinstance(item.get("source"), dict) else {},
                operation=str(item.get("operation") or ""),
                target_block_id=str(item.get("targetBlockId") or ""),
                before=str(item.get("before") or ""),
                after=str(item.get("after") or ""),
                reason=str(item.get("reason") or ""),
                affected_functions=[str(x) for x in item.get("affectedFunctions") or []],
                affected_blocks=[str(x) for x in item.get("affectedBlocks") or []],
                status=str(item.get("status") or "pending"),
            )
            for item in data.get("changes") or []
            if isinstance(item, dict)
        ]
        return AgentReadinessResult(
            readiness_run_id=str(data.get("readinessRunId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            role_match_run_id=str(data.get("roleMatchRunId") or ""),
            score=int(data.get("score") or 0),
            blocking=[str(x) for x in data.get("blocking") or []],
            important=[str(x) for x in data.get("important") or []],
            optional=[str(x) for x in data.get("optional") or []],
            questions=questions,
            changes=changes,
            status=str(data.get("status") or ""),
        )

    @staticmethod
    def _parse_agent_draft(data: dict) -> AgentDraft:
        readiness_raw = data.get("readiness")
        updated_at = _parse_datetime(data.get("updatedAt"))
        created_at = _parse_datetime(data.get("createdAt"))
        suggestions = [
            ApiClient._parse_agent_suggestion(item)
            for item in data.get("agentSuggestions") or []
            if isinstance(item, dict)
        ]
        return AgentDraft(
            draft_id=str(data.get("draftId") or ""),
            regulation_id=str(data.get("regulationId") or ""),
            role_match_run_id=str(data.get("roleMatchRunId") or ""),
            readiness_run_id=str(data.get("readinessRunId") or ""),
            title=str(data.get("title") or ""),
            position=str(data.get("position") or ""),
            department=str(data.get("department") or ""),
            status=str(data.get("status") or "draft"),
            progress=int(data.get("progress") or 0),
            readiness=ApiClient._parse_readiness(readiness_raw) if isinstance(readiness_raw, dict) else None,
            agent_suggestions=suggestions,
            updated_at=updated_at,
            created_at=created_at,
        )

    @staticmethod
    def _parse_question_chat(data: dict) -> QuestionChatSession:
        messages = [
            QuestionChatMessage(
                message_id=str(item.get("messageId") or ""),
                session_id=str(item.get("sessionId") or ""),
                role=str(item.get("role") or ""),
                content=str(item.get("content") or ""),
                structured=item.get("structured") if isinstance(item.get("structured"), dict) else {},
            )
            for item in data.get("messages") or []
            if isinstance(item, dict)
        ]
        return QuestionChatSession(
            session_id=str(data.get("sessionId") or ""),
            draft_id=str(data.get("draftId") or ""),
            readiness_run_id=str(data.get("readinessRunId") or ""),
            question_id=str(data.get("questionId") or ""),
            function_id=str(data.get("functionId") or ""),
            target_field=str(data.get("targetField") or ""),
            status=str(data.get("status") or ""),
            context=data.get("context") if isinstance(data.get("context"), dict) else {},
            messages=messages,
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


def _parse_sse_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "message", "text": raw}
    return payload if isinstance(payload, dict) else {"type": "message", "text": raw}


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
