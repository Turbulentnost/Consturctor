from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="Без названия")
    phase: Mapped[str] = mapped_column(String(64), nullable=False, default="document")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    document_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    document_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    attachments_meta: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    local_run: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    plan_agent_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    plan_run_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    exec_agent_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    exec_run_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    last_result: Mapped[str] = mapped_column(Text, nullable=False, default="")
    branch: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    pr_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
