from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FinanceImport(Base):
    __tablename__ = "finance_imports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="uploaded", index=True)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    media_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_by_fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    draft_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    validation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rows_valid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FinanceSalaryEntry(Base):
    __tablename__ = "finance_salary_entries"
    __table_args__ = (
        UniqueConstraint(
            "position_id",
            "effective_from",
            "revision",
            name="uq_finance_salary_position_date_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("org_positions.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    import_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("finance_imports.id"), nullable=False, index=True
    )
    replaced_entry_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("finance_salary_entries.id"), nullable=True
    )
    position_snapshot: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
