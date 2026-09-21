from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PositionKpiProfile(Base):
    """Норма KPI должности (не факт сотрудника)."""

    __tablename__ = "position_kpi_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    position_name: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    department: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    source_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    source_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PositionCompRule(Base):
    """ЦРП и правило премии. Суммы в рублях здесь не храним — в положении их нет."""

    __tablename__ = "position_comp_rules"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("position_kpi_profiles.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="RUB")
    bonus_kind: Mapped[str] = mapped_column(String(64), nullable=False, default="salary_times_crp_times_sum")
    bonus_base_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    bonus_human: Mapped[str] = mapped_column(Text, nullable=False, default="")
    payout_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PositionKpiMetric(Base):
    """Строка таблицы 5.2.4: показатель, вес, формула."""

    __tablename__ = "position_kpi_metrics"
    __table_args__ = (UniqueConstraint("profile_id", "code", name="uq_position_kpi_metrics_profile_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("position_kpi_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="%")
    plan_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    direction: Mapped[str] = mapped_column(String(16), nullable=False, default="higher")
    formula_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    formula_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    formula_human: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PositionKpiSource(Base):
    """Откуда план и факт по строке KPI."""

    __tablename__ = "position_kpi_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("position_kpi_metrics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    update_rule: Mapped[str] = mapped_column(Text, nullable=False, default="")
    extra_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
