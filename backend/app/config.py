from __future__ import annotations

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

    # App Postgres (users, avatars, future agent data). Not ERP.
    database_url: str = (
        "postgresql+psycopg://constructor:constructor@192.168.1.157:5435/constructor"
    )
    avatar_storage_dir: Path = BACKEND_ROOT / "storage" / "avatars"
    regulation_storage_dir: Path = BACKEND_ROOT / "storage" / "regulations"
    workflow_storage_dir: Path = BACKEND_ROOT / "storage" / "workflows"

    # IMAP (server-side tools only; desktop never executes imap.*)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_mailbox: str = "INBOX"

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


settings = Settings()
settings.avatar_storage_dir.mkdir(parents=True, exist_ok=True)
settings.regulation_storage_dir.mkdir(parents=True, exist_ok=True)
settings.workflow_storage_dir.mkdir(parents=True, exist_ok=True)
