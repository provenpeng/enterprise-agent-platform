"""Synthetic business tool verifies tenant scope and repeatable fixtures."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.business.demo_seed import DEMO_CASES, seed_demo_orders
from app.business.orders import OrderLookupTool
from app.models.demo_order import DemoOrder, DemoRefundAttempt, RefundStatus
from app.models.tenant import Tenant
from conftest import make_token


@pytest.mark.asyncio
async def test_seed_and_read_only_tool_are_tenant_scoped(api_client):
    client, _, sessions, _ = api_client
    first_tenant = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    second_tenant = uuid.uuid4()
    async with sessions() as db:
        db.add(Tenant(id=second_tenant, name="Second tenant"))
        await db.commit()
        assert await seed_demo_orders(db, first_tenant) == len(DEMO_CASES)
        assert await seed_demo_orders(db, first_tenant) == 0
        assert await seed_demo_orders(db, second_tenant) == len(DEMO_CASES)
        count = await db.scalar(select(func.count()).select_from(DemoOrder))
        assert count == 2 * len(DEMO_CASES)

        own = await OrderLookupTool(db, first_tenant).lookup("DEMO-WINDOW")
        assert own is not None
        assert own.refund_attempts[0].status == RefundStatus.FAILED
        assert own.refund_attempts[0].reason_code == "REFUND_WINDOW_EXPIRED"
        assert await OrderLookupTool(db, first_tenant).lookup("MISSING") is None

    viewer = {"Authorization": f"Bearer {make_token('test-user', role='viewer')}"}
    response = await client.get("/api/v1/business/orders/DEMO-WINDOW", headers=viewer)
    assert response.status_code == 200
    assert response.json()["order_id"] == "DEMO-WINDOW"
    assert (
        response.json()["refund_attempts"][0]["reason_code"] == "REFUND_WINDOW_EXPIRED"
    )
    assert (
        await client.get("/api/v1/business/orders/MISSING", headers=viewer)
    ).status_code == 404
    assert (
        await client.get("/api/v1/business/orders/bad_id", headers=viewer)
    ).status_code == 422
    assert (
        await client.post("/api/v1/business/orders/DEMO-WINDOW", headers=viewer)
    ).status_code == 405

    second = {
        "Authorization": f"Bearer {make_token('second', tenant_id=str(second_tenant))}"
    }
    assert (
        await client.get("/api/v1/business/orders/DEMO-WINDOW", headers=second)
    ).status_code == 200
    # The same public order ID can exist in each tenant without exposing the other tenant's row.
    async with sessions() as db:
        order = await db.get(DemoOrder, (second_tenant, "DEMO-WINDOW"))
        assert order is not None
        order.refundable_amount_cents = 1234
        await db.commit()
    assert (
        await client.get("/api/v1/business/orders/DEMO-WINDOW", headers=second)
    ).json()["refundable_amount_cents"] == 1234
    assert (
        await client.get("/api/v1/business/orders/DEMO-WINDOW", headers=viewer)
    ).json()["refundable_amount_cents"] == 10000


@pytest.mark.asyncio
async def test_seed_requires_real_tenant_and_fk_blocks_cross_tenant_attempt(api_client):
    _, _, sessions, _ = api_client
    tenant_id = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")
    async with sessions() as db:
        with pytest.raises(ValueError, match="Tenant does not exist"):
            await seed_demo_orders(db, uuid.uuid4())
        await seed_demo_orders(db, tenant_id)
        db.add(
            DemoRefundAttempt(
                tenant_id=uuid.uuid4(),
                order_id="DEMO-WINDOW",
                attempt_number=2,
                status=RefundStatus.FAILED,
                reason_code="GATEWAY_TIMEOUT",
                amount_cents=100,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
