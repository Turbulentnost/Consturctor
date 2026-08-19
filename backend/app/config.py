from __future__ import annotations

import json
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    erp_sql_server: str = "ii1"
    erp_sql_database: str = "erp_pm"
    erp_sql_driver: str = "ODBC Driver 18 for SQL Server"
    erp_sql_encrypt: str = "no"
    erp_sql_trusted_connection: bool = True
    erp_sql_user: str = ""
    erp_sql_password: str = ""

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    api_host: str = "0.0.0.0"
    api_port: int = 7812

    llm_provider: str = "stub"
    lm_studio_base_url: str = "http://192.168.1.157:1234"
    lm_studio_model: str = "ministral-3-14b-instruct-2512"
    ocr_pages_per_batch: int = 3
    claude_api_key: str = ""
    claudehub_base_url: str = "https://api.claudehub.fun"
    claudehub_model: str = "claude-sonnet-4.6"
    claudehub_fallback_model: str = "claude-haiku-4-5-20251001"
    claudehub_external_fallback_model: str = "gpt-5.6-sol"
    claudehub_max_blocks_per_chunk: int = 120
    chad_api_key: str = Field(default="", validation_alias="CHAD_AI")
    chad_base_url: str = "https://ask.chadgpt.ru/api"
    chad_model: str = "grok-4.1-fast-with-web-search"
    cursor_api_key: str = Field(default="", validation_alias="CURSOR_API_KEY")
    cursor_api_base_url: str = "https://api.cursor.com"
    cursor_regulation_model: str = "composer-2.5"
    cursor_workflow_model: str = "composer"

    database_url: str = (
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
    )
    avatar_storage_dir: Path = BACKEND_ROOT / "storage" / "avatars"
    regulation_storage_dir: Path = BACKEND_ROOT / "storage" / "regulations"
    workflow_storage_dir: Path = BACKEND_ROOT / "storage" / "workflows"

    tool_imap_url: str = "http://127.0.0.1:7821"
    tool_onec_url: str = "http://127.0.0.1:7822"
    tool_shell_url: str = "http://127.0.0.1:7823"
    tool_shell_native_url: str = "http://127.0.0.1:7828"
    tool_browser_url: str = "http://127.0.0.1:7824"
    tool_com_url: str = "http://127.0.0.1:7826"
    tool_fs_url: str = "http://127.0.0.1:7827"
    tool_desktop_host_url: str = "http://127.0.0.1:7830"
    tool_desktop_launcher_url: str = "http://127.0.0.1:7829"
    kpi_service_url: str = "http://127.0.0.1:7820"
    orchestrator_url: str = "http://127.0.0.1:7825"
    orchestrator_broker: str = "amqp://guest:guest@127.0.0.1:5672//"

    use_stubs: bool = True
    auth_stub: bool = False
    allow_local_registration: bool = True
    dev_mode: bool = False
    tool_manifest_path: str = str(BACKEND_ROOT / "data" / "tool_manifest.json")

    # IMAP (server-side tools only; desktop never executes imap.*)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"

    # TurboProject API (server-side tool turboproject; desktop only proxies)
    turboproject_api_base: str = ""
    turboproject_email: str = ""
    turboproject_password: str = ""
    turboproject_timeout_sec: float = 60.0

    # 1C OData (server-side tools onec.odata_*; desktop never executes onec.*)
    odata_base_url: str = ""
    odata_username: str = ""
    odata_password: str = ""
    odata_timeout_sec: float = 60.0
    odata_incoming_doc_entity: str = "Document_ТД_ВходящаяКорреспонденция"
    docflow_odata_base_url: str = ""
    docflow_odata_username: str = ""
    docflow_odata_password: str = ""
    erp_login: str = ""
    erp_password: str = ""
    onec_sql_allowlist: str = ""
    onec_odata_entity_allowlist: str = ""

    def resolved_tool_manifest_path(self) -> Path:
        raw = (self.tool_manifest_path or "").strip()
        if not raw:
            return BACKEND_ROOT / "data" / "tool_manifest.json"
        path = Path(raw)
        if not path.is_absolute():
            path = BACKEND_ROOT / path
        return path

    def allowed_tools_for_department(self, department: str) -> set[str] | None:
        if self.dev_mode:
            return None
        manifest_path = self.resolved_tool_manifest_path()
        if not manifest_path.is_file():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        dept = (department or "").strip()
        if not dept:
            return set(data.get("default", []))
        by_dept = data.get("by_department") or {}
        if dept in by_dept:
            return set(by_dept[dept])
        return set(data.get("default", []))

    def tool_service_url(self, tool_name: str, payload: dict | None = None) -> str | None:
        if tool_name.startswith("imap."):
            return self.tool_imap_url
        if tool_name.startswith("onec."):
            return self.tool_onec_url
        if tool_name.startswith("com."):
            return self.tool_com_url
        if tool_name.startswith("fs."):
            return self.tool_fs_url
        if tool_name.startswith("shell."):
            runtime = str((payload or {}).get("runtime", "")).strip().lower()
            if runtime == "native" and self.tool_shell_native_url:
                return self.tool_shell_native_url
            return self.tool_shell_url
        if tool_name.startswith("browser."):
            return self.tool_browser_url
        return None


settings = Settings()
settings.avatar_storage_dir.mkdir(parents=True, exist_ok=True)
settings.regulation_storage_dir.mkdir(parents=True, exist_ok=True)
settings.workflow_storage_dir.mkdir(parents=True, exist_ok=True)
