"""Tenant-scoped, read-only order lookup; never query by order ID alone."""

import uuid
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.demo_order import DemoOrder, DemoRefundAttempt
from app.schemas.business import OrderSnapshot, RefundAttemptSnapshot


class OrderReader(Protocol):
    async def lookup(self, order_id: str) -> OrderSnapshot | None: ...


class OrderServiceUnavailable(Exception):
    """The read-only business system did not return a trusted snapshot."""


class HttpOrderReader:
    """Tenant-scoped HTTP adapter; the model never controls its URL or headers."""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        tenant_id: uuid.UUID,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._tenant_id = tenant_id
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def lookup(self, order_id: str) -> OrderSnapshot | None:
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = await client.get(
                    f"/orders/{order_id}",
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "X-Tenant-ID": str(self._tenant_id),
                    },
                )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            snapshot = OrderSnapshot.model_validate(response.json())
            if snapshot.order_id != order_id:
                raise ValueError("Order service returned another order")
            return snapshot
        except (httpx.HTTPError, ValueError) as exc:
            raise OrderServiceUnavailable from exc


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
