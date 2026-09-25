"""Knowledge base search with tenant authorization before model calls."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import Principal, authorized_knowledge_base, get_principal
from app.api.embedding_provider import get_query_embeddings
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.retrieval import SearchRequest, SearchResponse
from app.services.retrieval import search_knowledge_base

router = APIRouter(prefix="/knowledge-bases/{knowledge_base_id}", tags=["retrieval"])


@router.post("/search", response_model=SearchResponse)
async def search(
    knowledge_base_id: uuid.UUID,
    payload: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    embeddings: Annotated[Embeddings, Depends(get_query_embeddings)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SearchResponse:
    # Authorization has completed; release its read transaction before the
    # network-bound embedding call. Retrieval opens a fresh scoped transaction.
    await db.rollback()
    hits = await search_knowledge_base(
        db,
        embeddings,
        tenant_id=principal.tenant_id,
        knowledge_base_id=knowledge_base_id,
        embedding_model=settings.embedding_model,
        query=payload.query,
        top_k=payload.top_k,
        min_score=payload.min_score,
        timeout_seconds=settings.retrieval_embedding_timeout_seconds,
    )
    return SearchResponse(knowledge_base_id=knowledge_base_id, hits=hits)
