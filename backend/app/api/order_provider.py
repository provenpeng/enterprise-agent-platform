"""Select the local demo data or configured read-only order service."""

from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Principal, get_principal
from app.business.orders import HttpOrderReader, OrderLookupTool, OrderReader
from app.core.config import Settings, get_settings
from app.db.session import get_db


def get_order_reader(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> OrderReader:
    if settings.order_api_base_url:
        if settings.order_api_token is None:
            raise HTTPException(
                status_code=503, detail="Order service is not configured"
            )
        return HttpOrderReader(
            base_url=str(settings.order_api_base_url),
            token=settings.order_api_token.get_secret_value(),
            tenant_id=principal.tenant_id,
            timeout_seconds=settings.order_api_timeout_seconds,
        )
    return OrderLookupTool(db, principal.tenant_id)
