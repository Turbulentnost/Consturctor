from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        # Board calendar and run history filter by owner + agent, newest first.
        Index("ix_agent_runs_user_wf_started", "user_id", "workflow_id", "started_at"),
        # Stale-run sweep filters by owner + status.
        Index("ix_agent_runs_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="started")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="chat")
    trigger_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    trigger_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    trigger_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    events_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
