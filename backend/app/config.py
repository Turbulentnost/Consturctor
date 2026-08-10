from __future__ import annotations

import json
from pathlib import Path

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

    database_url: str = (
        "postgresql+psycopg://constructor:constructor@127.0.0.1:5432/constructor"
    )

    tool_imap_url: str = "http://127.0.0.1:7821"
    tool_onec_url: str = "http://127.0.0.1:7822"
    tool_shell_url: str = "http://127.0.0.1:7823"
    tool_browser_url: str = "http://127.0.0.1:7824"
    kpi_service_url: str = "http://127.0.0.1:7820"
    orchestrator_url: str = "http://127.0.0.1:7825"
    orchestrator_broker: str = "amqp://guest:guest@127.0.0.1:5672//"

    use_stubs: bool = True
    auth_stub: bool = False
    tool_manifest_path: str = ""

    def tool_service_url(self, tool_name: str) -> str | None:
        if tool_name.startswith("imap."):
            return self.tool_imap_url
        if tool_name.startswith("onec."):
            return self.tool_onec_url
        if tool_name.startswith("shell."):
            return self.tool_shell_url
        if tool_name.startswith("browser."):
            return self.tool_browser_url
        return None

    def allowed_tools_for_department(self, department: str) -> set[str] | None:
        path = (self.tool_manifest_path or "").strip()
        if not path:
            return None
        manifest_path = Path(path)
        if not manifest_path.is_file():
            return None
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        dept = department.strip()
        if not dept:
            return set(data.get("default", []))
        by_dept = data.get("by_department") or {}
        if dept in by_dept:
            return set(by_dept[dept])
        return set(data.get("default", []))


settings = Settings()
