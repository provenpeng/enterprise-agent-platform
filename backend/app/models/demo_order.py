"""Synthetic order data used only by the demo business tool."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class PaymentStatus(str, enum.Enum):
    PAID = "PAID"
    UNPAID = "UNPAID"
    REFUNDED = "REFUNDED"


class RefundStatus(str, enum.Enum):
    PENDING = "PENDING"
    FAILED = "FAILED"
    SUCCEEDED = "SUCCEEDED"


class DemoOrder(Base):
    __tablename__ = "demo_orders"
    __table_args__ = (
        CheckConstraint(
            "total_amount_cents >= 0", name="ck_demo_orders_total_nonnegative"
        ),
        CheckConstraint(
            "refundable_amount_cents >= 0", name="ck_demo_orders_refundable_nonnegative"
        ),
        CheckConstraint(
            "refundable_amount_cents <= total_amount_cents",
            name="ck_demo_orders_refundable_not_above_total",
        ),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    order_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="demo_payment_status"), nullable=False
    )
    total_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    refundable_amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    refund_attempts: Mapped[list["DemoRefundAttempt"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", passive_deletes=True
    )


class DemoRefundAttempt(Base):
    __tablename__ = "demo_refund_attempts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "order_id"],
            ["demo_orders.tenant_id", "demo_orders.order_id"],
            ondelete="CASCADE",
            name="fk_demo_refund_attempts_order",
        ),
        CheckConstraint(
            "attempt_number > 0", name="ck_demo_refund_attempt_number_positive"
        ),
        CheckConstraint(
            "amount_cents > 0", name="ck_demo_refund_attempt_amount_positive"
        ),
        CheckConstraint(
            "status != 'FAILED' OR reason_code IS NOT NULL",
            name="ck_demo_refund_failed_reason",
        ),
        UniqueConstraint(
            "tenant_id",
            "order_id",
            "attempt_number",
            name="uq_demo_refund_attempt_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    order_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        Enum(RefundStatus, name="demo_refund_status"), nullable=False
    )
    reason_code: Mapped[str | None] = mapped_column(String(64))
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    order: Mapped[DemoOrder] = relationship(back_populates="refund_attempts")
