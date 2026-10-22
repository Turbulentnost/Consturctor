"""Карточка внешнего несерийного заказа (ТЗ-ИИ-ВЗ-01)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ExternalOrder(Base):
    __tablename__ = "external_orders"
    __table_args__ = (Index("ix_external_orders_stage_status", "stage", "status"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    customer: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    inn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    contact: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    product: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    order_type: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    priority: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="request")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    route: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    owners_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    sections_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    payment_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    checks: Mapped[list[ExternalOrderCheck]] = relationship(
        "ExternalOrderCheck", cascade="all, delete-orphan"
    )
    diffs: Mapped[list[ExternalOrderDiff]] = relationship(
        "ExternalOrderDiff", cascade="all, delete-orphan"
    )
    risks: Mapped[list[ExternalOrderRisk]] = relationship(
        "ExternalOrderRisk", cascade="all, delete-orphan"
    )
    decisions: Mapped[list[ExternalOrderDecision]] = relationship(
        "ExternalOrderDecision", cascade="all, delete-orphan"
    )
    findings: Mapped[list[ExternalOrderFinding]] = relationship(
        "ExternalOrderFinding", cascade="all, delete-orphan"
    )
    documents: Mapped[list[ExternalOrderDocument]] = relationship(
        "ExternalOrderDocument", cascade="all, delete-orphan"
    )
    audit: Mapped[list[ExternalOrderAudit]] = relationship(
        "ExternalOrderAudit", cascade="all, delete-orphan"
    )
    gaps: Mapped[list[ExternalOrderGap]] = relationship(
        "ExternalOrderGap", cascade="all, delete-orphan"
    )
    baselines: Mapped[list[ExternalOrderBaseline]] = relationship(
        "ExternalOrderBaseline", cascade="all, delete-orphan"
    )
    tasks: Mapped[list[ExternalOrderTask]] = relationship(
        "ExternalOrderTask", cascade="all, delete-orphan"
    )
    lines: Mapped[list[ExternalOrderLine]] = relationship(
        "ExternalOrderLine", cascade="all, delete-orphan"
    )
    notices: Mapped[list[ExternalOrderNotice]] = relationship(
        "ExternalOrderNotice", cascade="all, delete-orphan"
    )


class ExternalOrderCheck(Base):
    __tablename__ = "external_order_checks"
    __table_args__ = (Index("ix_external_order_checks_order", "order_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False)
    gate: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="not_started")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    blocking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confirmed_by: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class ExternalOrderDiff(Base):
    __tablename__ = "external_order_diffs"
    __table_args__ = (Index("ix_external_order_diffs_order", "order_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    area: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="material")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    left_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    right_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ExternalOrderRisk(Base):
    __tablename__ = "external_order_risks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    impact: Mapped[str] = mapped_column(Text, nullable=False, default="")
    measure: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    created_by: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class ExternalOrderDecision(Base):
    __tablename__ = "external_order_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    protocol: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    decision: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    allowed_stage: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conditions_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    baseline_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    decided_by: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExternalOrderFinding(Base):
    __tablename__ = "external_order_findings"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location: Mapped[str] = mapped_column(Text, nullable=False, default="")
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    proposed_by: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class ExternalOrderDocument(Base):
    __tablename__ = "external_order_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    file_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    stored_path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ExternalOrderAudit(Base):
    __tablename__ = "external_order_audit"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_fio: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    before_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    after_value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ExternalOrderGap(Base):
    __tablename__ = "external_order_gaps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ExternalOrderBaseline(Base):
    __tablename__ = "external_order_baselines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    composition: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mcr: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    margin: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    bdds: Mapped[str] = mapped_column(Text, nullable=False, default="")
    deadlines: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[str] = mapped_column(String(512), nullable=False, default="")


class ExternalOrderTask(Base):
    __tablename__ = "external_order_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="stage")
    owner_role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    depends_on: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_ref: Mapped[str] = mapped_column(Text, nullable=False, default="")


class ExternalOrderLine(Base):
    __tablename__ = "external_order_lines"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    qty: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    amount: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    change: Mapped[str] = mapped_column(String(16), nullable=False, default="")


class ExternalOrderNotice(Base):
    __tablename__ = "external_order_notices"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("external_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mail_status: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
