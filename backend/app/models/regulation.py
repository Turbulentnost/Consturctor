from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
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


class ReadinessRun(Base):
    __tablename__ = "readiness_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    regulation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("regulations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_match_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("role_match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RegulationRevision(Base):
    __tablename__ = "regulation_revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    regulation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("regulations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    readiness_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("readiness_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    protocol_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentDraft(Base):
    __tablename__ = "agent_drafts"
    __table_args__ = (UniqueConstraint("role_match_run_id", name="uq_agent_drafts_role_match_run"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    regulation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("regulations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_match_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("role_match_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    readiness_run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="draft")
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class QuestionChatSession(Base):
    __tablename__ = "question_chat_sessions"
    __table_args__ = (
        UniqueConstraint("draft_id", "question_id", name="uq_question_chat_draft_question"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    draft_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    readiness_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("readiness_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    function_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    target_field: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="active")
    context_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class QuestionChatMessage(Base):
    __tablename__ = "question_chat_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("question_chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(String(4000), nullable=False, default="")
    structured_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
