from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.exc import OperationalError

from app.db.session import get_db
from app.main import app


@pytest.mark.asyncio
async def test_health_succeeds_when_database_responds() -> None:
    db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_returns_503_when_database_is_unavailable() -> None:
    db = AsyncMock()
    db.execute.side_effect = OperationalError("SELECT 1", {}, Exception("connection refused"))
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/v1/health")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
