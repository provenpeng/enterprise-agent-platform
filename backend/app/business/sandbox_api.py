"""Local-only read-only order service for exercising the HTTP adapter."""

import hmac
import os
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.business.orders import OrderLookupTool
from app.db.session import get_db
from app.schemas.business import OrderSnapshot

app = FastAPI(title="Local Order Sandbox")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/orders/{order_id}", response_model=OrderSnapshot)
async def get_order(
    order_id: Annotated[
        str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
    x_tenant_id: Annotated[str | None, Header()] = None,
) -> OrderSnapshot:
    expected = os.getenv("ORDER_SANDBOX_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Sandbox token is not configured")
    if not authorization or not hmac.compare_digest(
        authorization, f"Bearer {expected}"
    ):
        raise HTTPException(status_code=401, detail="Invalid service token")
    try:
        tenant_id = uuid.UUID(x_tenant_id or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant ID") from exc
    snapshot = await OrderLookupTool(db, tenant_id).lookup(order_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return snapshot
