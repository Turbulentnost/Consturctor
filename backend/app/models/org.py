from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OrgUnit(Base):
    """Подразделение управленческой структуры 1С (без ликвидированных)."""

    __tablename__ = "org_units"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    parent_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    head_fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrgMember(Base):
    """Сотрудник с текущим назначением. user_id — v8users 1С, если есть учётная запись."""

    __tablename__ = "org_members"

    fio_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    position: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    unit_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    department: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
