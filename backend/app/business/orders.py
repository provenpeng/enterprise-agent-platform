"""Tenant-scoped, read-only order lookup; never query by order ID alone."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demo_order import DemoOrder, DemoRefundAttempt
from app.schemas.business import OrderSnapshot, RefundAttemptSnapshot


class OrderLookupTool:
    def __init__(self, db: AsyncSession, tenant_id: uuid.UUID) -> None:
        self._db = db
        self._tenant_id = tenant_id

    async def lookup(self, order_id: str) -> OrderSnapshot | None:
        order = await self._db.scalar(
            select(DemoOrder).where(
                DemoOrder.tenant_id == self._tenant_id,
                DemoOrder.order_id == order_id,
            )
        )
        if order is None:
            return None
        attempts = await self._db.scalars(
            select(DemoRefundAttempt)
            .where(
                DemoRefundAttempt.tenant_id == self._tenant_id,
                DemoRefundAttempt.order_id == order_id,
            )
            .order_by(DemoRefundAttempt.attempt_number)
        )
        return OrderSnapshot(
            order_id=order.order_id,
            payment_status=order.payment_status,
            total_amount_cents=order.total_amount_cents,
            refundable_amount_cents=order.refundable_amount_cents,
            currency=order.currency,
            created_at=order.created_at,
            refund_attempts=[
                RefundAttemptSnapshot(
                    attempt_number=attempt.attempt_number,
                    status=attempt.status,
                    reason_code=attempt.reason_code,
                    amount_cents=attempt.amount_cents,
                    created_at=attempt.created_at,
                )
                for attempt in attempts
            ],
        )
