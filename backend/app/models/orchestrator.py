from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserOrchestrator(Base):
    """Per-user position KPI board (employee work, not agent-run KPI)."""

    __tablename__ = "user_orchestrators"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="empty")
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_agent_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tiles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sdk_agent_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    forming_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calculating_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    formed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
