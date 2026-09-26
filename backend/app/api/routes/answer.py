"""Cited knowledge base question answering."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.answer_provider import get_answer_generator
from app.api.auth import Principal, authorized_knowledge_base, get_principal
from app.api.embedding_provider import get_query_embeddings
from app.api.model_admission import model_request_slot
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase
from app.rag.answer_generator import AnswerGenerator
from app.schemas.answer import AskRequest, AskResponse
from app.services.answer import answer_question

router = APIRouter(prefix="/knowledge-bases/{knowledge_base_id}", tags=["answers"])


@router.post("/ask", response_model=AskResponse)
async def ask(
    knowledge_base_id: uuid.UUID,
    payload: AskRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    _model_slot: Annotated[None, Depends(model_request_slot)],
    embeddings: Annotated[Embeddings, Depends(get_query_embeddings)],
    generator: Annotated[AnswerGenerator, Depends(get_answer_generator)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AskResponse:
    return await answer_question(
        db,
        embeddings,
        generator,
        tenant_id=principal.tenant_id,
        knowledge_base_id=knowledge_base_id,
        embedding_space_id=settings.embedding_space_id,
        question=payload.query,
        top_k=payload.top_k,
        min_score=payload.min_score,
        embedding_timeout_seconds=settings.retrieval_embedding_timeout_seconds,
        generation_timeout_seconds=settings.answer_generation_timeout_seconds,
    )
