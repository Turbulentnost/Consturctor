from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.base import Base

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=40,
    pool_recycle=1800,
    pool_timeout=10,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    # Import models so metadata is populated.
    from app.models import agent_run as _agent_run  # noqa: F401
    from app.models import notification as _notification  # noqa: F401
    from app.models import orchestrator as _orchestrator  # noqa: F401
    from app.models import regulation as _regulation  # noqa: F401
    from app.models import trigger as _trigger  # noqa: F401
    from app.models import user as _user  # noqa: F401
    from app.models import workflow as _workflow  # noqa: F401
    from app.modules.chat import models as _chat  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """Add new columns to existing tables without a full migration tool.

    Shared DB (constructor @ 192.168.1.157:5435) may already have a `users` table
    from AIConstructor with a different shape (e.g. avatar_key instead of avatar_path).
    """
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'users'
                """
            )
        ).fetchall()
        existing = {str(r[0]) for r in rows}
        alters: list[str] = []
        if "department_changed_at" not in existing:
            alters.append("ADD COLUMN department_changed_at TIMESTAMPTZ NULL")
        if "position" not in existing:
            alters.append("ADD COLUMN position VARCHAR(512) NOT NULL DEFAULT ''")
        if "avatar_path" not in existing:
            alters.append("ADD COLUMN avatar_path VARCHAR(1024) NULL")
        if "updated_at" not in existing:
            alters.append(
                "ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
            )
        if "department" not in existing:
            alters.append("ADD COLUMN department VARCHAR(512) NOT NULL DEFAULT ''")
        if "activity_status" not in existing:
            alters.append("ADD COLUMN activity_status VARCHAR(16) NOT NULL DEFAULT 'online'")
        if "is_support" not in existing:
            alters.append("ADD COLUMN is_support BOOLEAN NOT NULL DEFAULT FALSE")
        if existing and "fio" not in existing:
            alters.append("ADD COLUMN fio VARCHAR(512) NOT NULL DEFAULT ''")
        if existing:
            for clause in alters:
                conn.execute(text(f"ALTER TABLE users {clause}"))
        trigger_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'agent_triggers'
                """
            )
        ).fetchall()
        trigger_cols = {str(r[0]) for r in trigger_rows}
        if trigger_cols and "interval_seconds" not in trigger_cols:
            conn.execute(
                text(
                    "ALTER TABLE agent_triggers "
                    "ADD COLUMN interval_seconds INTEGER NOT NULL DEFAULT 0"
                )
            )
        notif_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'notifications'
                """
            )
        ).fetchall()
        notif_cols = {str(r[0]) for r in notif_rows}
        if notif_cols and "read_at" not in notif_cols:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN read_at TIMESTAMPTZ NULL"))
        if notif_cols and "run_id" not in notif_cols:
            conn.execute(
                text("ALTER TABLE notifications ADD COLUMN run_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        run_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'agent_runs'
                """
            )
        ).fetchall()
        run_cols = {str(r[0]) for r in run_rows}
        if run_cols and "events_json" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN events_json JSON NOT NULL DEFAULT '[]'")
            )
        if run_cols and "trigger_id" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN trigger_id VARCHAR(64) NOT NULL DEFAULT ''")
            )
        if run_cols and "trigger_kind" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN trigger_kind VARCHAR(32) NOT NULL DEFAULT ''")
            )
        if run_cols and "trigger_reason" not in run_cols:
            conn.execute(
                text("ALTER TABLE agent_runs ADD COLUMN trigger_reason TEXT NOT NULL DEFAULT ''")
            )
        creation_rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = 'regulation_creation_drafts'
                """
            )
        ).fetchall()
        creation_cols = {str(r[0]) for r in creation_rows}
        if creation_cols and "interview_json" not in creation_cols:
            conn.execute(
                text(
                    "ALTER TABLE regulation_creation_drafts "
                    "ADD COLUMN interview_json JSON NOT NULL DEFAULT '{}'"
                )
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
