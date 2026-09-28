"""The HTTP order boundary enforces tenant scope and fails closed."""

import uuid

import httpx
import pytest

from app.api.order_provider import get_order_reader
from app.business.demo_seed import seed_demo_orders
from app.business.orders import HttpOrderReader, OrderServiceUnavailable
from app.business.sandbox_api import app as sandbox_app
from app.db.session import get_db
from app.main import app

TENANT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "enterprise-agent-platform:test-user")


@pytest.mark.asyncio
async def test_http_connector_reads_sandbox_with_tenant_scope(
    api_client, monkeypatch
) -> None:
    _, _, sessions, _ = api_client
    async with sessions() as db:
        await seed_demo_orders(db, TENANT_ID)

    async def override_db():
        async with sessions() as db:
            yield db

    monkeypatch.setenv("ORDER_SANDBOX_TOKEN", "sandbox-secret")
    sandbox_app.dependency_overrides[get_db] = override_db
    try:
        reader = HttpOrderReader(
            base_url="http://sandbox",
            token="sandbox-secret",
            tenant_id=TENANT_ID,
            timeout_seconds=3,
            transport=httpx.ASGITransport(app=sandbox_app),
        )
        found = await reader.lookup("DEMO-WINDOW")
        assert found is not None
        assert found.order_id == "DEMO-WINDOW"
        assert found.refund_attempts[-1].reason_code == "REFUND_WINDOW_EXPIRED"
        assert await reader.lookup("MISSING") is None

        outsider = HttpOrderReader(
            base_url="http://sandbox",
            token="sandbox-secret",
            tenant_id=uuid.uuid4(),
            timeout_seconds=3,
            transport=httpx.ASGITransport(app=sandbox_app),
        )
        assert await outsider.lookup("DEMO-WINDOW") is None
        wrong_token = HttpOrderReader(
            base_url="http://sandbox",
            token="wrong",
            tenant_id=TENANT_ID,
            timeout_seconds=3,
            transport=httpx.ASGITransport(app=sandbox_app),
        )
        with pytest.raises(OrderServiceUnavailable):
            await wrong_token.lookup("DEMO-WINDOW")
    finally:
        sandbox_app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, json={"order_id": "DIFFERENT"}),
        httpx.Response(200, content=b"invalid json"),
    ],
)
async def test_http_connector_rejects_bad_upstream_responses(
    response: httpx.Response,
) -> None:
    reader = HttpOrderReader(
        base_url="https://orders.example",
        token="service-secret",
        tenant_id=TENANT_ID,
        timeout_seconds=3,
        transport=httpx.MockTransport(lambda request: response),
    )
    with pytest.raises(OrderServiceUnavailable):
        await reader.lookup("DEMO-WINDOW")


@pytest.mark.asyncio
async def test_http_connector_never_uses_caller_supplied_tenant() -> None:
    seen = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404)

    reader = HttpOrderReader(
        base_url="https://orders.example",
        token="service-secret",
        tenant_id=TENANT_ID,
        timeout_seconds=3,
        transport=httpx.MockTransport(respond),
    )
    assert await reader.lookup("DEMO-WINDOW") is None
    assert seen[0].headers["X-Tenant-ID"] == str(TENANT_ID)
    assert seen[0].headers["Authorization"] == "Bearer service-secret"
    assert str(seen[0].url) == "https://orders.example/orders/DEMO-WINDOW"


@pytest.mark.asyncio
async def test_connector_timeout_is_sanitized_by_business_api(api_client) -> None:
    client, _, _, _ = api_client

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private upstream detail", request=request)

    reader = HttpOrderReader(
        base_url="https://orders.example",
        token="service-secret",
        tenant_id=TENANT_ID,
        timeout_seconds=0.01,
        transport=httpx.MockTransport(timeout),
    )
    app.dependency_overrides[get_order_reader] = lambda: reader
    response = await client.get("/api/v1/business/orders/DEMO-WINDOW")
    assert response.status_code == 503
    assert response.json() == {"detail": "Order service is unavailable"}
    assert "private upstream detail" not in response.text
