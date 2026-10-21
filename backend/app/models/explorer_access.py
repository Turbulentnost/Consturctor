"""Предложения серверного агента по доступу к файлам базы знаний."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExplorerAccessSuggestion(Base):
    """Одно предложение: кому и какой ключ выдать. Ключ появляется только после согласия владельца."""

    __tablename__ = "explorer_access_suggestions"
    __table_args__ = (
        Index("ix_explorer_access_suggestions_owner_status", "owner_user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    owner_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    # user | department | all | private
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    grantee_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    grantee_label: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # read | write | пусто для private
    permission: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quote: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # pending | accepted | dismissed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExplorerAccessAgentState(Base):
    """Курсор серверного агента: с какого момента смотреть изменённые файлы и чем кончился прошлый прогон."""

    __tablename__ = "explorer_access_agent_state"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_status: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_plan: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
