from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RegulationDocument(Base):
    __tablename__ = "regulations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_name: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    is_scan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RoleMatchRun(Base):
    __tablename__ = "role_match_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    regulation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("regulations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[str] = mapped_column(String(256), nullable=False)
    department: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
