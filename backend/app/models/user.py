from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppUser(Base):
    """Constructor app user mirrored from ERP login (not 1C passwords)."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # ERP v8users id
    fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    department: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    avatar_path: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    activity_status: Mapped[str] = mapped_column(String(16), nullable=False, default="online")
    is_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    department_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserKpiPin(Base):
    """PIN-код сотрудника для просмотра зарплаты в KPI. Хранятся только соль и хеш."""

    __tablename__ = "user_kpi_pins"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    salt: Mapped[str] = mapped_column(String(64), nullable=False)
    pin_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
