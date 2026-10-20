"""Снимок поручения АСТ00 и вердикты агента «Проверка поручений к закрытию»."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AssignmentReview(Base):
    """Карточка поручения на момент проверки. Закрытое больше не читаем из 1С."""

    __tablename__ = "assignment_reviews"
    __table_args__ = (
        UniqueConstraint("ref_key", name="uq_assignment_reviews_ref_key"),
        Index("ix_assignment_reviews_number", "number"),
        Index("ix_assignment_reviews_open_checked", "open", "checked_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    ref_key: Mapped[str] = mapped_column(String(64), nullable=False)
    number: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    open: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    topic: Mapped[str] = mapped_column(Text, nullable=False, default="")
    basis: Mapped[str] = mapped_column(Text, nullable=False, default="")
    manager: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    organization: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    reporter: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    secretary: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    due: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    weekly_report_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    final_report_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    lines_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    files_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    conclusion: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    workflow_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    tasks: Mapped[list[AssignmentReviewTask]] = relationship(
        "AssignmentReviewTask", back_populates="review", cascade="all, delete-orphan"
    )
    verdicts: Mapped[list[AssignmentReviewVerdict]] = relationship(
        "AssignmentReviewVerdict", back_populates="review", cascade="all, delete-orphan"
    )


class AssignmentReviewTask(Base):
    """Задача Документооборота внутри снимка поручения."""

    __tablename__ = "assignment_review_tasks"
    __table_args__ = (
        UniqueConstraint("review_id", "n", name="uq_assignment_review_tasks_n"),
        Index("ix_assignment_review_tasks_task_id", "task_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assignment_reviews.id", ondelete="CASCADE"), nullable=False, index=True
    )
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    chain: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    performer: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    author: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    begin: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    due: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    returns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    comments_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    files_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    open_check_task_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    open_execute_task_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    review: Mapped[AssignmentReview] = relationship("AssignmentReview", back_populates="tasks")
    verdicts: Mapped[list[AssignmentReviewVerdict]] = relationship(
        "AssignmentReviewVerdict", back_populates="task", cascade="all, delete-orphan"
    )


class AssignmentReviewVerdict(Base):
    """Вердикт агента по задаче. На экране — последняя запись."""

    __tablename__ = "assignment_review_verdicts"
    __table_args__ = (Index("ix_assignment_review_verdicts_review", "review_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    review_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assignment_reviews.id", ondelete="CASCADE"), nullable=False
    )
    task_row_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("assignment_review_tasks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    verdict: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    advice: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    review: Mapped[AssignmentReview] = relationship("AssignmentReview", back_populates="verdicts")
    task: Mapped[AssignmentReviewTask] = relationship("AssignmentReviewTask", back_populates="verdicts")
