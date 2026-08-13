from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db.base import Base

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    # Import models so metadata is populated.
    from app.models import regulation as _regulation  # noqa: F401
    from app.models import user as _user  # noqa: F401
    from app.models import workflow as _workflow  # noqa: F401

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
        if not existing:
            return
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
        if "fio" not in existing:
            alters.append("ADD COLUMN fio VARCHAR(512) NOT NULL DEFAULT ''")
        for clause in alters:
            conn.execute(text(f"ALTER TABLE users {clause}"))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
