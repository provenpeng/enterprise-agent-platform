"""Knowledge base Q&A history for the authenticated subject."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Principal, authorized_knowledge_base, get_principal
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.conversation import ConversationDetail, ConversationSummary
from app.services.conversations import (
    delete_conversation,
    get_conversation,
    list_conversations,
)

router = APIRouter(
    prefix="/knowledge-bases/{knowledge_base_id}/conversations", tags=["conversations"]
)


@router.get("", response_model=list[ConversationSummary])
async def list_history(
    knowledge_base_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await list_conversations(
        db,
        tenant_id=principal.tenant_id,
        owner_sub=principal.subject,
        knowledge_base_id=knowledge_base_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def read_history(
    knowledge_base_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return await get_conversation(
        db,
        tenant_id=principal.tenant_id,
        owner_sub=principal.subject,
        knowledge_base_id=knowledge_base_id,
        conversation_id=conversation_id,
        limit=limit,
        offset=offset,
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_history(
    knowledge_base_id: uuid.UUID,
    conversation_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
) -> Response:
    await delete_conversation(
        db,
        tenant_id=principal.tenant_id,
        owner_sub=principal.subject,
        knowledge_base_id=knowledge_base_id,
        conversation_id=conversation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
