import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import (
    Principal,
    current_tenant,
    get_principal,
    require_admin,
    tenant_knowledge_base,
)
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseRead

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> KnowledgeBase:
    require_admin(principal)
    await current_tenant(db, principal)
    knowledge_base = KnowledgeBase(
        name=payload.name,
        description=payload.description,
        owner_sub=principal.subject,
        tenant_id=principal.tenant_id,
    )
    db.add(knowledge_base)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="Knowledge base name already exists"
        ) from exc
    return knowledge_base


@router.get("", response_model=list[KnowledgeBaseRead])
async def list_knowledge_bases(
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KnowledgeBase]:
    result = await db.scalars(
        select(KnowledgeBase)
        .where(KnowledgeBase.tenant_id == principal.tenant_id)
        .order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
) -> KnowledgeBase:
    return await tenant_knowledge_base(db, knowledge_base_id, principal)
