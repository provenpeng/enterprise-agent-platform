import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseRead


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-bases"])


@router.post("", response_model=KnowledgeBaseRead, status_code=status.HTTP_201_CREATED)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBase:
    knowledge_base = KnowledgeBase(name=payload.name, description=payload.description)
    db.add(knowledge_base)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Knowledge base name already exists") from exc
    return knowledge_base


@router.get("", response_model=list[KnowledgeBaseRead])
async def list_knowledge_bases(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[KnowledgeBase]:
    result = await db.scalars(
        select(KnowledgeBase).order_by(KnowledgeBase.created_at.desc(), KnowledgeBase.id.desc())
    )
    return list(result)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBaseRead)
async def get_knowledge_base(
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeBase:
    knowledge_base = await db.get(KnowledgeBase, knowledge_base_id)
    if knowledge_base is None:
        raise HTTPException(status_code=404, detail="Knowledge base not found")
    return knowledge_base
