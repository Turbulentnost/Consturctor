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
    from app.models import user as _user  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_columns()


def _ensure_columns() -> None:
    """Add new columns to existing tables without a full migration tool."""
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'users'
                """
            )
        ).fetchall()
        existing = {str(r[0]) for r in rows}
        if "department_changed_at" not in existing:
            conn.execute(
                text(
                    "ALTER TABLE users "
                    "ADD COLUMN department_changed_at TIMESTAMPTZ NULL"
                )
            )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
