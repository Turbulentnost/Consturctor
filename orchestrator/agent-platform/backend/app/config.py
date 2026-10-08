from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_host: str = "127.0.0.1"
    api_port: int = 7820

    # Та же база, что у Constructor (backend/app/config.py: database_url). Таблицы Constructor
    # только читаем; пишем лишь в свою схему turbotest.
    constructor_database_url: str = (
        "postgresql+psycopg://constructor:constructor@192.168.1.157:5435/constructor"
    )
    # Аватары лежат на диске бэкенда Constructor, в БД только путь к файлу.
    constructor_api_url: str = "http://192.168.1.157:7812"
    constructor_connect_timeout: int = 8
    constructor_sync_enabled: bool = True
    constructor_sync_seconds: int = 60

    # Сессия Constructor для инструментов, которые исполняет его backend (1С, IMAP, users,
    # TurboProject). Либо готовый JWT, либо ФИО и пароль для POST /api/v1/auth/login.
    constructor_api_token: str = ""
    constructor_login_fio: str = ""
    constructor_login_password: str = ""
    # Рабочие папки агентов для файловых инструментов. Пусто — %LOCALAPPDATA%/TurboTest/agent_workspaces;
    # чтобы видеть файлы живых агентов, укажите %LOCALAPPDATA%/Constructor/agent_workspaces.
    tools_workspaces_root: str = ""
    tools_default_timeout_seconds: int = 90

    # PLATFORM_CONFIGS_DIR. Одна подпапка — одна конфигурация, описание в её config.json.
    platform_configs_dir: Path = BACKEND_ROOT.parent / "platform" / "configs"
    # Служебные конфигурации платформы (тестировщик инструментов): в списке конфигураций их нет.
    platform_internal_dir: Path = BACKEND_ROOT.parent / "platform" / "internal"
    # Агенты, сессии и рабочие папки запусков платформы.
    platform_data_dir: Path = BACKEND_ROOT.parent / "platform" / "data"
    # Диалог, файлы каталога и снимок конфигурации прогона — схема turbotest в базе Constructor.
    platform_history_enabled: bool = True
    # Агенты конфигураций с plan_instruction (план, последний прогон, инструменты) пишутся в
    # turbotest.agents той же базы Constructor — их видят и запускают все пользователи.
    platform_shared_enabled: bool = True

    # Передаются процессу конфигурации: ключ Cursor SDK и desktop-часть Constructor для MCP.
    cursor_api_key: str = ""
    # Облачный агент Cursor (REST /v1/agents) заполняет паспорт и рисует иконку агентов
    # конфигураций с plan_instruction после их успешного прогона.
    cursor_api_base_url: str = "https://api.cursor.com"
    cursor_cloud_model: str = "composer-2.5"
    platform_profile_enabled: bool = True
    constructor_desktop_dir: str = ""
    # Под этим пользователем MCP входит в Constructor (constructor_api_url): users.current всегда он.
    constructor_user_fio: str = ""
    constructor_user_password: str = ""


settings = Settings()
