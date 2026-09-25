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


class PositionKpiModule(Base):
    """Исходник калькулятора KPI. Один модуль на показатель должности, общий для всех сотрудников."""

    __tablename__ = "position_kpi_modules"
    __table_args__ = (
        UniqueConstraint("profile_id", "metric_code", name="uq_position_kpi_modules_profile_code"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("position_kpi_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False)
    module_name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    tests: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PositionKpiDailyFact(Base):
    """Дневной снимок посчитанных KPI должности."""

    __tablename__ = "position_kpi_daily_facts"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "day",
            "period_from",
            "period_to",
            name="uq_position_kpi_daily_facts_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("position_kpi_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PositionKpiSubjectFact(Base):
    """Дневной снимок KPI конкретного сотрудника. Каталог и модули общие для должности."""

    __tablename__ = "position_kpi_subject_facts"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "subject",
            "day",
            "period_from",
            "period_to",
            name="uq_position_kpi_subject_facts_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("position_kpi_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    subject_fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    day: Mapped[date] = mapped_column(Date, nullable=False)
    period_from: Mapped[date] = mapped_column(Date, nullable=False)
    period_to: Mapped[date] = mapped_column(Date, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class PositionKpiBuild(Base):
    """Сессия конструирования KPI-модуля по методике должности."""

    __tablename__ = "position_kpi_builds"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    position_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="awaiting_file")
    cursor_agent_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    extracted_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    catalog_draft_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    modules_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    profile_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PositionKpiBuildMessage(Base):
    __tablename__ = "position_kpi_build_messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    build_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("position_kpi_builds.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    structured_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
