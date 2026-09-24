"""Read-only demo business data for an authenticated tenant member."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Principal, get_principal
from app.business.orders import OrderLookupTool
from app.db.session import get_db
from app.schemas.business import OrderSnapshot


router = APIRouter(prefix="/business/orders", tags=["demo-business"])


@router.get("/{order_id}", response_model=OrderSnapshot)
async def get_demo_order(
    order_id: Annotated[
        str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> OrderSnapshot:
    snapshot = await OrderLookupTool(db, principal.tenant_id).lookup(order_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return snapshot
