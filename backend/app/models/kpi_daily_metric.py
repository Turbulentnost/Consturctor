from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkplaceKpiDailyMetric(Base):
    """Дневные значения KPI сотрудника (выполнение / SLA) для графика динамики."""

    __tablename__ = "workplace_kpi_daily_metrics"
    __table_args__ = (
        UniqueConstraint("user_id", "day", name="uq_workplace_kpi_daily_user_day"),
        Index("ix_workplace_kpi_daily_user_day", "user_id", "day"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    tasks_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sla_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
