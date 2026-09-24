from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PlatformTask(Base):
    """Задача, поставленная в Оркестраторе одним сотрудником другому."""

    __tablename__ = "platform_tasks"
    __table_args__ = (
        Index("ix_platform_tasks_author", "author_user_id"),
        Index("ix_platform_tasks_assignee", "assignee_user_id"),
        Index("ix_platform_tasks_status_due", "status", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    author_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    author_fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    assignee_user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    assignee_fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # open | done | rejected
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    status_comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    overdue_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Приёмка постановщиком: исполнитель закрыл задачу, автор подтверждает до конца дня.
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rework_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlatformTaskFile(Base):
    __tablename__ = "platform_task_files"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("platform_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    uploaded_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
