"""Create and read Q&A history only within its tenant, owner, and knowledge base."""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, ConversationTurn
from app.models.knowledge_base import KnowledgeBase
from app.schemas.answer import AskResponse
from app.schemas.conversation import ConversationDetail, ConversationTurnRead
from app.services.errors import NotFound


def _owned(tenant_id: uuid.UUID, owner_sub: str, knowledge_base_id: uuid.UUID) -> tuple:
    return (
        Conversation.tenant_id == tenant_id,
        Conversation.owner_sub == owner_sub,
        Conversation.knowledge_base_id == knowledge_base_id,
    )


async def validate_conversation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    owner_sub: str,
    knowledge_base_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
) -> None:
    if conversation_id is None:
        return
    found = await db.scalar(
        select(Conversation.id).where(
            Conversation.id == conversation_id,
            *_owned(tenant_id, owner_sub, knowledge_base_id),
        )
    )
    await db.rollback()
    if found is None:
        raise NotFound("Conversation not found")


async def append_verified_turn(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    owner_sub: str,
    knowledge_base_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    question: str,
    answer: AskResponse,
) -> AskResponse:
    """Commit the question and verified final answer as one turn."""
    if conversation_id is None:
        knowledge_base = await db.scalar(
            select(KnowledgeBase.id).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.tenant_id == tenant_id,
            )
        )
        if knowledge_base is None:
            await db.rollback()
            raise NotFound("Knowledge base not found")
        conversation = Conversation(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            owner_sub=owner_sub,
            knowledge_base_id=knowledge_base_id,
            title=question[:120],
        )
        db.add(conversation)
    else:
        conversation = await db.scalar(
            select(Conversation)
            .where(
                Conversation.id == conversation_id,
                *_owned(tenant_id, owner_sub, knowledge_base_id),
            )
            .with_for_update()
        )
        if conversation is None:
            await db.rollback()
            raise NotFound("Conversation not found")
        conversation.updated_at = await db.scalar(select(func.now()))
    db.add(
        ConversationTurn(
            conversation_id=conversation.id,
            question=question,
            answer=answer.answer,
            grounded=answer.grounded,
            citations=[
                citation.model_dump(mode="json") for citation in answer.citations
            ],
        )
    )
    await db.commit()
    return answer.model_copy(update={"conversation_id": conversation.id})


async def list_conversations(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    owner_sub: str,
    knowledge_base_id: uuid.UUID,
    offset: int,
    limit: int,
) -> list[Conversation]:
    rows = await db.scalars(
        select(Conversation)
        .where(*_owned(tenant_id, owner_sub, knowledge_base_id))
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(rows)


async def get_conversation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    owner_sub: str,
    knowledge_base_id: uuid.UUID,
    conversation_id: uuid.UUID,
    offset: int,
    limit: int,
) -> ConversationDetail:
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            *_owned(tenant_id, owner_sub, knowledge_base_id),
        )
    )
    if conversation is None:
        raise NotFound("Conversation not found")
    recent = list(
        await db.scalars(
            select(ConversationTurn)
            .where(ConversationTurn.conversation_id == conversation.id)
            .order_by(ConversationTurn.created_at.desc(), ConversationTurn.id.desc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return ConversationDetail(
        id=conversation.id,
        knowledge_base_id=conversation.knowledge_base_id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        turns=[
            ConversationTurnRead.model_validate(turn)
            for turn in reversed(recent[:limit])
        ],
        has_older=len(recent) > limit,
    )


async def delete_conversation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    owner_sub: str,
    knowledge_base_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> None:
    result = await db.execute(
        delete(Conversation).where(
            Conversation.id == conversation_id,
            *_owned(tenant_id, owner_sub, knowledge_base_id),
        )
    )
    if result.rowcount == 0:
        await db.rollback()
        raise NotFound("Conversation not found")
    await db.commit()
