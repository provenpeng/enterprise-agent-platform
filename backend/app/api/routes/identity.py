"""Return claims only after the normal bearer-token verification."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.auth import Principal, get_principal
from app.schemas.identity import IdentityRead

router = APIRouter(tags=["identity"])


@router.get("/me", response_model=IdentityRead)
async def get_identity(
    principal: Annotated[Principal, Depends(get_principal)],
) -> IdentityRead:
    return IdentityRead(
        subject=principal.subject,
        tenant_id=principal.tenant_id,
        role=principal.role,
    )
