"""Read-only business tool result shared by API and Agent workflow."""

from datetime import datetime

from pydantic import BaseModel

from app.models.demo_order import PaymentStatus, RefundStatus


class RefundAttemptSnapshot(BaseModel):
    attempt_number: int
    status: RefundStatus
    reason_code: str | None
    amount_cents: int
    created_at: datetime


class OrderSnapshot(BaseModel):
    order_id: str
    payment_status: PaymentStatus
    total_amount_cents: int
    refundable_amount_cents: int
    currency: str
    created_at: datetime
    refund_attempts: list[RefundAttemptSnapshot]
