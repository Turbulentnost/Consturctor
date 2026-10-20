from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../infrastructure/.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Корпоративная платформа ИИ-агентов"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"
    ENVIRONMENT: Literal["dev", "test", "ope", "prod"] = "dev"
    DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = False
    SECRET_KEY: str = "change_me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    PASSWORD_MIN_LENGTH: int = 8
    ONEC_AUTH_API_BASE_URL: str = "http://192.168.0.247:8000/api/v1"
    ONEC_TOKEN_MAX_AGE_HOURS: int = 4
    BACKEND_CORS_ORIGINS: str = (
        "http://localhost:5173,http://127.0.0.1:5173,http://192.168.1.157:5173"
    )
    BACKEND_CORS_ALLOW_CREDENTIALS: bool = True
    BACKEND_CORS_ALLOW_METHODS: str = "*"
    BACKEND_CORS_ALLOW_HEADERS: str = "*"

    POSTGRES_HOST: str = "192.168.1.157"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "1234"
    POSTGRES_DB: str = "ai_agents"

    REDIS_HOST: str = "192.168.1.157"
    REDIS_PORT: int = 16379
    REDIS_DB: int = 0
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    CELERY_VISIBILITY_TIMEOUT_SECONDS: int = 60 * 60 * 24
    KB_INDEXING_STALE_AFTER_SECONDS: int = 60 * 45
    KB_INDEXING_RECOVERY_INTERVAL_SECONDS: int = 60 * 10
    KB_INDEXING_RECOVERY_MAX_JOBS: int = 5
    KB_DOCUMENT_PARSE_TIMEOUT_SECONDS: int = 60 * 10

    QDRANT_HOST: str = "192.168.1.157"
    QDRANT_PORT: int = 6333
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION: str = "knowledge_base_bge_m3"
    QDRANT_VECTOR_SIZE: int = 1024

    # Режим поиска по базе знаний: "semantic" — чистый векторный (смысловой)
    # поиск; "hybrid" — вектор + полнотекстовый поиск по ключевым словам.
    # Гибрид устойчивее на коротких запросах («База данных»): смысловой поиск
    # дополняется точными совпадениями слов, итог объединяется через RRF.
    KB_SEARCH_MODE: str = "hybrid"
    # Минимальная косинусная близость, ниже которой фрагмент не показывается
    # (0 — без отсечки). Помогает не выдавать нерелевантные фрагменты.
    KB_SEARCH_MIN_SCORE: float = 0.0
    # Максимальное время (сек) на формирование «Предварительного ответа» через
    # LLM. По истечении показываем самый релевантный фрагмент без синтеза.
    KB_SEARCH_ANSWER_TIMEOUT: float = 45.0
    # Модели LM Studio для генерации ответа по фрагментам (через запятую).
    # Перебираются по порядку: если модель недоступна или вернула пустой
    # ответ — пробуем следующую.
    KB_SEARCH_ANSWER_MODELS: str = (
        "openai/gpt-oss-120b,qwen/qwen3.5-9b,yandexgpt-5-lite-8b-instruct"
    )

    MINIO_ENDPOINT: str = "192.168.1.157:9000"
    # Адрес MinIO для presigned URL в браузере (LAN/IP). В Docker backend использует minio:9000,
    # а клиенту отдаём публичный host:port, иначе <img src> не загрузится.
    MINIO_PUBLIC_ENDPOINT: str = ""
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "ai-documents"
    MINIO_USER_FILES_BUCKET: str = "ai-user-files"
    MINIO_SECURE: bool = False
    AVATAR_MAX_UPLOAD_SIZE_BYTES: int = 5 * 1024 * 1024
    AVATAR_ALLOWED_CONTENT_TYPES: str = "image/jpeg,image/png,image/webp"
    DOCUMENT_MAX_UPLOAD_SIZE_BYTES: int = 50 * 1024 * 1024
    DOCUMENT_ALLOWED_CONTENT_TYPES: str = (
        "application/pdf,"
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document,"
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,"
        "application/msword,"
        "application/vnd.ms-excel,"
        "text/plain,"
        "text/csv,"
        "image/png,"
        "image/jpeg,"
        "image/webp"
    )

    # Общий LLM-шлюз (прочие задачи платформы).
    LLM_GATEWAY_BASE_URL: str = ""
    LLM_GATEWAY_API_KEY: str | None = None
    OPENAI_API_KEY_CLAUDE: str | None = None
    OPENAI_API_KEY: str | None = None
    LLM_DEFAULT_MODEL: str = ""
    LLM_EMBEDDING_MODEL: str = ""
    # Конструктор агентов: Claude → fallback в LM Studio (отдельно от OCR).
    AGENT_BUILDER_CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
    AGENT_BUILDER_FALLBACK_BASE_URL: str = ""
    AGENT_BUILDER_FALLBACK_MODEL: str = "openai/gpt-oss-120b"
    # Структурное извлечение nd_control (DocumentCard, анализ отдела).
    ND_CONTROL_EXTRACTION_MODEL: str = "openai/gpt-oss-120b"
    ND_CONTROL_EXTRACTION_LLM_TIMEOUT_SECONDS: int = 1200
    ND_TEMPLATE_CLASSIFICATION_MODEL: str | None = None
    ND_CONTROL_UML_MODEL: str | None = None
    ND_CONTROL_UML_LLM_TIMEOUT_SECONDS: int = 180
    # OCR / vision для PDF и изображений через выбранную vision-модель LM Studio.
    VISION_LM_STUDIO_BASE_URL: str = ""
    VISION_LM_STUDIO_MODEL: str = "qwen/qwen3.5-9b"
    # Для сопоставления вложений важнее быстро получить признаки, чем ждать
    # полный OCR многостраничного скана до десяти минут.
    VISION_OCR_TIMEOUT_SECONDS: int = 45
    VISION_OCR_MAX_TOKENS: int = 600
    EMBEDDINGS_PROVIDER: str = "local"
    EMBEDDINGS_MODEL: str = "BAAI/bge-m3"
    EMBEDDINGS_VECTOR_SIZE: int = 1024
    EMBEDDINGS_DEVICE: str = "cuda"
    EMBEDDINGS_BATCH_SIZE: int = 16
    EMBEDDINGS_TIMEOUT_SECONDS: int = 60
    EMBEDDINGS_ALLOW_CPU_FALLBACK: bool = True
    EMBEDDINGS_MAX_TEXT_LENGTH: int = 20000
    BROWSER_ALLOWED_DOMAINS: str = (
        "1c.company.local,docs.company.local,portal.company.local,edo.company.local,"
        "wttr.in,pogoda.yandex.ru,yandex.ru,gismeteo.ru,www.gismeteo.ru,meteoinfo.ru,"
        "duckduckgo.com,html.duckduckgo.com,www.duckduckgo.com"
    )
    BROWSER_BLOCKED_SCHEMES: str = "file:,javascript:,data:"
    BROWSER_MAX_TIMEOUT_SECONDS: int = 60
    BROWSER_POLL_INTERVAL_SECONDS: float = 1.0
    # Runtime Sandbox: разрешить открытый веб (поиск + произвольные сайты), минуя allowlist.
    # Внутренние/loopback/private IP, localhost, исполняемые файлы и запрещённые схемы блокируются всегда.
    # Задеплоенные production-агенты остаются на ограничительном allowlist (allow_open_web=False).
    BROWSER_SANDBOX_OPEN_WEB: bool = True

    # Network filesystem tool: только чтение внутри allowlist-корней (UNC/локальные).
    # Prefer \\host\share — bare \\host is not a browsable Path on Windows.
    FS_ALLOWED_ROOTS: str = r"\\192.168.1.198\Files"
    FS_MAX_READ_BYTES: int = 2_000_000
    FS_MAX_LIST_ENTRIES: int = 200
    FS_FUZZY_MIN_SCORE: float = 0.72
    FS_RESOLVE_MAX_CANDIDATES: int = 8
    FS_SEARCH_MAX_ENTRIES: int = 5000

    # 1С: ERP OData — значения только из .env (см. .env.example).
    ONEC_ODATA_URL: str = ""
    ONEC_ODATA_USER: str = ""
    ONEC_ODATA_PASSWORD: str = ""
    ONEC_ODATA_TIMEOUT: int = 120
    ONEC_MEETING_MEMO_THEME: str = ""
    ONEC_CORPORATE_EMAIL_DOMAIN: str = "turbo-don.ru"
    ONEC_NOTIFICATION_DEFAULT_RECIPIENT_FIOS: str = ""
    ONEC_NOTIFICATION_SOURCE_USER_FIO: str = ""

    # 1С: документооборот.
    # HTTP hs/dterp: TasksID, Tasks, TasksII/User (исполнения документов).
    # Inbox «Мои задачи» — SOAP /doc/ws/dm.1cws (те же DOK_HTTP_*).
    DOK_HTTP_SERVER: str = ""
    DOK_HTTP_PORT: int = 81
    DOK_HTTP_USER: str = ""
    DOK_HTTP_PASSWORD: str = ""
    DOK_HTTP_TIMEOUT: int = 30
    DOK_HTTP_BASE_PATH: str = "/doc"
    DOK_HTTP_SERVICE: str = "dterp"
    DOK_HTTP_TEMPLATE: str = "Tasks"
    DOK_HTTP_SUFFIX: str = ""
    MEETING_DASHBOARD_CACHE_ENABLED: bool = True
    MEETING_DASHBOARD_CACHE_TTL_SECONDS: int = 60 * 60 * 24
    MEETING_DASHBOARD_CACHE_WARMUP_ENABLED: bool = True
    MEETING_DASHBOARD_CACHE_WARMUP_HOURS: str = "10,15"
    MEETING_DASHBOARD_CACHE_WARMUP_MINUTE: int = 0
    MEETING_DASHBOARD_CACHE_WARMUP_TIMEZONE: str = "Europe/Moscow"
    MEETING_DASHBOARD_ONEC_LIMIT: int = 50

    # Dashboard контроля поручений: дневной кэш Redis + Celery-прогрев.
    TASKS_DASHBOARD_CACHE_ENABLED: bool = True
    TASKS_DASHBOARD_CACHE_TTL_SECONDS: int = 60 * 60 * 24
    TASKS_DASHBOARD_CACHE_WARMUP_ENABLED: bool = True
    TASKS_DASHBOARD_CACHE_WARMUP_HOURS: str = "7,15"
    TASKS_DASHBOARD_CACHE_WARMUP_MINUTE: int = 0
    TASKS_DASHBOARD_CACHE_WARMUP_TIMEZONE: str = "Europe/Moscow"
    # CSV ФИО руководителей для прогрева (по умолчанию — Амураль).
    TASKS_DASHBOARD_CACHE_WARMUP_FIOS: str = "Амураль Игорь Борисович"
    TASKS_DASHBOARD_CACHE_WARMUP_LIMIT: int = 500

    # Сопоставление вложений 1С с мероприятиями. По умолчанию LLM выключен:
    # включать в production только после проверки hs/dtw/files/{fileId}.
    PORUCHENIYA_MAPPING_LLM_ENABLED: bool = False
    PORUCHENIYA_MAPPING_LLM_MODEL: str | None = None
    PORUCHENIYA_MAPPING_LLM_TIMEOUT_SECONDS: int = 90
    PORUCHENIYA_MAPPING_LLM_MAX_ATTEMPTS: int = 2
    PORUCHENIYA_MAPPING_AUTO_CONFIDENCE: float = 0.75
    PORUCHENIYA_MAPPING_AUTO_MARGIN: float = 0.15
    PORUCHENIYA_MAPPING_MAX_CANDIDATES: int = 8
    PORUCHENIYA_MAPPING_MAX_TEXT_CHARS: int = 12_000
    PORUCHENIYA_MAPPING_OCR_ENABLED: bool = True
    PORUCHENIYA_MAPPING_MAX_OCR_PAGES: int = 1
    PORUCHENIYA_MAPPING_CLEANUP_ENABLED: bool = True
    PORUCHENIYA_MAPPING_CLEANUP_DAYS: int = 90
    # Если Celery потерял задачу, бронь __pending__ зависает и UI крутит
    # «ИИ проверяет вложения…». Через этот интервал dispatch снимает бронь
    # и ставит анализ заново.
    PORUCHENIYA_MAPPING_PENDING_STALE_SECONDS: int = 180
    # Оценка «можно ли закрывать задачу» LLM по ответу исполнителя и вложениям.
    # Запускается только вручную кнопкой «Запустить проверку».
    PORUCHENIYA_CLOSE_EVAL_ENABLED: bool = True
    PORUCHENIYA_CLOSE_EVAL_LLM_MODEL: str | None = None
    PORUCHENIYA_CLOSE_EVAL_TIMEOUT_SECONDS: int = 120
    PORUCHENIYA_CLOSE_EVAL_MAX_ATTEMPTS: int = 2
    PORUCHENIYA_CLOSE_EVAL_INCLUDE_FILE_TEXT: bool = True
    PORUCHENIYA_CLOSE_EVAL_MAX_FILES: int = 4
    PORUCHENIYA_CLOSE_EVAL_MAX_FILE_CHARS: int = 6_000
    # Дельта-опрос метаданных 1С. LLM вызывается только для новой ревизии файла
    # либо изменившегося контекста мероприятий, не для каждого поручения.
    PORUCHENIYA_MAPPING_POLL_ENABLED: bool = False
    PORUCHENIYA_MAPPING_POLL_INTERVAL_SECONDS: int = 30 * 60
    PORUCHENIYA_MAPPING_POLL_FIOS: str = ""
    PORUCHENIYA_MAPPING_POLL_LIMIT: int = 500
    PORUCHENIYA_MAPPING_POLL_MAX_FILES: int = 10
    PORUCHENIYA_MAPPING_INITIAL_LOOKBACK_DAYS: int = 14

    # Недельный отчёт АСТ: ежедневные снимки статусов (Пн–Пт).
    TASKS_WEEKLY_SNAPSHOT_ENABLED: bool = True
    TASKS_WEEKLY_SNAPSHOT_HOUR: int = 18
    TASKS_WEEKLY_SNAPSHOT_MINUTE: int = 0
    TASKS_WEEKLY_SNAPSHOT_TTL_SECONDS: int = 60 * 60 * 24 * 90
    TASKS_WEEKLY_SNAPSHOT_LIMIT: int = 500
    TASKS_WEEKLY_SNAPSHOT_TIMEZONE: str = "Europe/Moscow"
    MEETING_TOPIC_SIMILARITY_USE_EMBEDDINGS: bool = True
    MEETING_TOPIC_SIMILARITY_THRESHOLD: float = 0.85
    MEETING_TOPIC_SIMILARITY_WEIGHT_TOPIC: float = 0.50
    MEETING_TOPIC_SIMILARITY_WEIGHT_PARTICIPANTS: float = 0.30
    MEETING_TOPIC_SIMILARITY_WEIGHT_DETAILS: float = 0.20
    MEETING_TOPIC_SIMILARITY_MIN_TOPIC_SCORE: float = 0.70
    SCHEDULED_MEETINGS_ARCHIVE_ENABLED: bool = True
    SCHEDULED_MEETINGS_ARCHIVE_HOUR: int = 1
    SCHEDULED_MEETINGS_ARCHIVE_MINUTE: int = 0
    SCHEDULED_MEETINGS_CARD_SYNC_ENABLED: bool = True
    SCHEDULED_MEETINGS_CARD_SYNC_HOUR: int = 6
    SCHEDULED_MEETINGS_CARD_SYNC_MINUTE: int = 0
    MEETING_MEMO_SERIES_LLM_ENABLED: bool = True
    MEETING_MEMO_SERIES_LLM_MODEL: str | None = None
    MEETING_MEMO_SERIES_LLM_MAX_TOKENS: int = 1500
    MEETING_PROTOCOL_DRAFT_ENABLED: bool = True
    MEETING_PROTOCOL_DRAFT_MINUTES_BEFORE: int = 10
    MEETING_PROTOCOL_DRAFT_NUMBER_TEMPLATE: str = "AUTO_{memo_number}_{date}"
    MEETING_PROTOCOL_DRAFT_TEMPLATE_PREFIX: str | None = None
    MEETING_PROTOCOL_DISPATCH_LOOKAHEAD_HOURS: int = 48
    MEETING_PROTOCOL_DISPATCH_CATCHUP_GRACE_MINUTES: int = 30
    MEETING_PROTOCOL_DISPATCH_BEAT_ENABLED: bool = True
    MEETING_PROTOCOL_DISPATCH_BEAT_HOURS: str = "8,12,16"
    MEETING_PROTOCOL_DISPATCH_BEAT_MINUTE: int = 0

    # Outlook / Exchange (COM-календарь, EWS, SMTP) — значения из .env.
    OUTLOOK_EMAIL: str = ""
    OUTLOOK_PASSWORD: str = ""
    OUTLOOK_SERVER: str = ""
    OUTLOOK_WEB_APP_URL: str = ""
    OUTLOOK_MAILBOX: str = ""
    OUTLOOK_TIMEZONE: str = "Europe/Moscow"
    OUTLOOK_SMTP_HOST: str = ""
    OUTLOOK_SMTP_PORT: int = 587
    OUTLOOK_SMTP_TLS: str = "true"
    OUTLOOK_SMTP_FROM: str = ""
    OUTLOOK_COMPANY_CALENDAR: str = "calendar@turbo-don.ru"

    # TurboProject (MS Project + 1С) — значения из .env.
    TURBO_PROJECT_API_BASE_URL: str = ""
    TURBO_PROJECT_EMAIL: str = ""
    TURBO_PROJECT_PASSWORD: str = ""
    TURBO_PROJECT_TIMEOUT: int = 60
    TURBO_PROJECT_SERIES_SYNC_ENABLED: bool = True
    # Нижний порог file_id (включительно). Старые проекты не трогаем. 0 = без порога.
    TURBO_PROJECT_SERIES_MIN_FILE_ID: int = 433
    # Доп. фильтр по uploaded_at за N дней (0 = выкл; uploaded_at в TP часто = дата обновления).
    TURBO_PROJECT_SERIES_UPLOADED_WITHIN_DAYS: int = 0
    TURBO_PROJECT_SERIES_SYNC_HOUR: int = 7
    TURBO_PROJECT_SERIES_SYNC_MINUTE: int = 30
    # Опрос TurboProject при открытии вкладки «график» (GET /meetings/scheduled).
    TURBO_PROJECT_SERIES_SYNC_ON_SCHEDULE_LIST: bool = True
    TURBO_PROJECT_SERIES_SYNC_COOLDOWN_SECONDS: int = 300
    # Дневной кэш всех проектов (Redis) + сводка к закрытию/открытию → уведомление 1С.
    TURBO_PROJECT_DAILY_CACHE_ENABLED: bool = True
    TURBO_PROJECT_DAILY_CACHE_ON_SCHEDULE_LIST: bool = True
    TURBO_PROJECT_CLOSING_SOON_BUSINESS_DAYS: int = 10
    TURBO_PROJECT_OPENING_SOON_CALENDAR_DAYS: int = 5
    TURBO_PROJECT_SUMMARY_NOTIFY_ENABLED: bool = True
    TURBO_PROJECT_SUMMARY_NOTIFY_FIOS: str = "Лапина Арина Антоновна"

    @property
    def cors_origins(self) -> list[str]:
        return self._parse_csv(self.BACKEND_CORS_ORIGINS)

    @property
    def cors_allow_methods(self) -> list[str]:
        return self._parse_csv(self.BACKEND_CORS_ALLOW_METHODS)

    @property
    def cors_allow_headers(self) -> list[str]:
        return self._parse_csv(self.BACKEND_CORS_ALLOW_HEADERS)

    @property
    def document_allowed_content_types(self) -> list[str]:
        return self._parse_csv(self.DOCUMENT_ALLOWED_CONTENT_TYPES)

    @property
    def avatar_allowed_content_types(self) -> list[str]:
        return self._parse_csv(self.AVATAR_ALLOWED_CONTENT_TYPES)

    @property
    def browser_allowed_domains(self) -> list[str]:
        return self._parse_csv(self.BROWSER_ALLOWED_DOMAINS)

    @property
    def browser_blocked_schemes(self) -> list[str]:
        return self._parse_csv(self.BROWSER_BLOCKED_SCHEMES)

    @property
    def fs_allowed_roots(self) -> list[str]:
        return self._parse_csv(self.FS_ALLOWED_ROOTS)

    @property
    def porucheniya_mapping_poll_fios(self) -> list[str]:
        configured = self.PORUCHENIYA_MAPPING_POLL_FIOS or self.TASKS_DASHBOARD_CACHE_WARMUP_FIOS
        return self._parse_csv(configured)

    def _parse_csv(self, value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field
    @property
    def DATABASE_URL_SYNC(self) -> str:
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field
    @property
    def minio_presign_endpoint(self) -> str:
        """Host:port для presigned URL в браузере."""
        public = self.MINIO_PUBLIC_ENDPOINT.strip()
        if public:
            return public
        internal_host = self.MINIO_ENDPOINT.split(":", 1)[0].strip()
        if internal_host in {"minio", "localhost", "127.0.0.1"}:
            # Backend в Docker: MinIO снаружи на POSTGRES_HOST:9000 (проброс порта compose).
            return f"{self.POSTGRES_HOST}:9000"
        return self.MINIO_ENDPOINT

    @computed_field
    @property
    def REDIS_URL(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @computed_field
    @property
    def QDRANT_URL(self) -> str:
        return f"http://{self.QDRANT_HOST}:{self.QDRANT_PORT}"

    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/1"

    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/2"


@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()
