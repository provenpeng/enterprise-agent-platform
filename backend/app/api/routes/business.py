"""Read-only demo business data for an authenticated tenant member."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path

from app.api.order_provider import get_order_reader
from app.business.orders import OrderReader, OrderServiceUnavailable
from app.schemas.business import OrderSnapshot

router = APIRouter(prefix="/business/orders", tags=["demo-business"])


@router.get("/{order_id}", response_model=OrderSnapshot)
async def get_demo_order(
    order_id: Annotated[
        str, Path(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    ],
    reader: Annotated[OrderReader, Depends(get_order_reader)],
) -> OrderSnapshot:
    try:
        snapshot = await reader.lookup(order_id)
    except OrderServiceUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Order service is unavailable"
        ) from exc
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return snapshot
