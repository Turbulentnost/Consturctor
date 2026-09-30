from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
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


class OrgPosition(Base):
    """Должность из справочника 1С (_Reference164)."""

    __tablename__ = "org_positions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False, default="", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrgPerson(Base):
    """Устойчивый справочник физических лиц 1С для финансовой истории."""

    __tablename__ = "org_people"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    fio: Mapped[str] = mapped_column(String(512), nullable=False, default="", index=True)
    fio_key: Mapped[str] = mapped_column(String(512), nullable=False, default="", index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    position_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("org_positions.id"), nullable=True, default=None, index=True
    )
    position: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    unit_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    department: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class OrgMember(Base):
    """Сотрудник с текущим назначением. user_id — v8users 1С, если есть учётная запись."""

    __tablename__ = "org_members"

    fio_key: Mapped[str] = mapped_column(String(512), primary_key=True)
    fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    person_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None, index=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    position: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    position_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("org_positions.id"), nullable=True, default=None, index=True
    )
    unit_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    department: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdminPanelAssignment(Base):
    """Единственная административная панель, назначенная должности."""

    __tablename__ = "admin_panel_assignments"

    position_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("org_positions.id"), primary_key=True
    )
    panel_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AdminUserPanelAssignment(Base):
    """Персональная административная панель с приоритетом над должностью."""

    __tablename__ = "admin_user_panel_assignments"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    panel_key: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
