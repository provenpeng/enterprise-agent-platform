"""Idempotent, explicit synthetic data for business workflow demonstrations."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demo_order import (
    DemoOrder,
    DemoRefundAttempt,
    PaymentStatus,
    RefundStatus,
)
from app.models.tenant import Tenant

DEMO_TIMESTAMP = datetime(2026, 1, 2, 9, 0, tzinfo=timezone.utc)

# All identifiers and values are fictitious. Each tenant gets its own rows.
DEMO_CASES = (
    (
        "DEMO-WINDOW",
        PaymentStatus.PAID,
        10000,
        10000,
        RefundStatus.FAILED,
        "REFUND_WINDOW_EXPIRED",
        10000,
    ),
    (
        "DEMO-AMOUNT",
        PaymentStatus.PAID,
        10000,
        2000,
        RefundStatus.FAILED,
        "AMOUNT_EXCEEDS_REFUNDABLE",
        5000,
    ),
    (
        "DEMO-GATEWAY",
        PaymentStatus.PAID,
        10000,
        10000,
        RefundStatus.FAILED,
        "GATEWAY_TIMEOUT",
        10000,
    ),
    (
        "DEMO-SUCCESS",
        PaymentStatus.REFUNDED,
        10000,
        0,
        RefundStatus.SUCCEEDED,
        None,
        10000,
    ),
)


async def seed_demo_orders(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Insert missing fixture rows for an existing tenant; return new order count."""
    if await db.scalar(select(Tenant.id).where(Tenant.id == tenant_id)) is None:
        raise ValueError("Tenant does not exist")
    inserted = 0
    for order_id, payment, total, refundable, status, reason, amount in DEMO_CASES:
        attempt_at = DEMO_TIMESTAMP + timedelta(
            days=32 if reason == "REFUND_WINDOW_EXPIRED" else 1
        )
        result = await db.execute(
            insert(DemoOrder)
            .values(
                tenant_id=tenant_id,
                order_id=order_id,
                payment_status=payment,
                total_amount_cents=total,
                refundable_amount_cents=refundable,
                currency="CNY",
                created_at=DEMO_TIMESTAMP,
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "order_id"])
            .returning(DemoOrder.order_id)
        )
        inserted += int(result.scalar_one_or_none() is not None)
        await db.execute(
            insert(DemoRefundAttempt)
            .values(
                id=uuid.uuid5(
                    uuid.NAMESPACE_URL, f"demo-refund:{tenant_id}:{order_id}:1"
                ),
                tenant_id=tenant_id,
                order_id=order_id,
                attempt_number=1,
                status=status,
                reason_code=reason,
                amount_cents=amount,
                created_at=attempt_at,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "order_id", "attempt_number"],
                # Repair older synthetic fixtures where all attempts had the
                # order creation timestamp, including the expired-window case.
                set_={"created_at": attempt_at},
            )
        )
    await db.commit()
    return inserted
