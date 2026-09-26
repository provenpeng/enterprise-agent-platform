"""Cited knowledge base question answering, including provisional SSE output."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
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
from app.services.answer import answer_question, retrieve_answer_hits, stream_answer
from app.services.conversations import append_verified_turn, validate_conversation
from app.services.errors import UpstreamUnavailable

router = APIRouter(prefix="/knowledge-bases/{knowledge_base_id}", tags=["answers"])
logger = logging.getLogger(__name__)


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
    await validate_conversation(
        db,
        tenant_id=principal.tenant_id,
        owner_sub=principal.subject,
        knowledge_base_id=knowledge_base_id,
        conversation_id=payload.conversation_id,
    )
    answer = await answer_question(
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
    return await append_verified_turn(
        db,
        tenant_id=principal.tenant_id,
        owner_sub=principal.subject,
        knowledge_base_id=knowledge_base_id,
        conversation_id=payload.conversation_id,
        question=payload.query,
        answer=answer,
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


@router.post(
    "/ask/stream",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {"schema": {"type": "string"}}}}},
)
async def ask_stream(
    request: Request,
    knowledge_base_id: uuid.UUID,
    payload: AskRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[Principal, Depends(get_principal)],
    _knowledge_base: Annotated[KnowledgeBase, Depends(authorized_knowledge_base)],
    _model_slot: Annotated[None, Depends(model_request_slot)],
    embeddings: Annotated[Embeddings, Depends(get_query_embeddings)],
    generator: Annotated[AnswerGenerator, Depends(get_answer_generator)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    # Authorization and retrieval finish before response headers are sent, so
    # their failures retain normal HTTP status codes. The database transaction
    # is released before any model stream is consumed.
    await validate_conversation(
        db,
        tenant_id=principal.tenant_id,
        owner_sub=principal.subject,
        knowledge_base_id=knowledge_base_id,
        conversation_id=payload.conversation_id,
    )
    hits = await retrieve_answer_hits(
        db,
        embeddings,
        tenant_id=principal.tenant_id,
        knowledge_base_id=knowledge_base_id,
        embedding_space_id=settings.embedding_space_id,
        question=payload.query,
        top_k=payload.top_k,
        min_score=payload.min_score,
        embedding_timeout_seconds=settings.retrieval_embedding_timeout_seconds,
    )

    async def events() -> AsyncIterator[str]:
        yield _sse("status", {"phase": "generating" if hits else "no_evidence"})
        try:
            async for update in stream_answer(
                generator,
                knowledge_base_id=knowledge_base_id,
                question=payload.query,
                hits=hits,
                generation_timeout_seconds=settings.answer_generation_timeout_seconds,
            ):
                if isinstance(update, str):
                    yield _sse("delta", {"text": update, "provisional": True})
                else:
                    final = await append_verified_turn(
                        db,
                        tenant_id=principal.tenant_id,
                        owner_sub=principal.subject,
                        knowledge_base_id=knowledge_base_id,
                        conversation_id=payload.conversation_id,
                        question=payload.query,
                        answer=update,
                    )
                    yield _sse("final", final.model_dump(mode="json"))
        except Exception as exc:
            if not isinstance(exc, UpstreamUnavailable):
                logger.exception(
                    "Unexpected answer stream failure for %s", knowledge_base_id
                )
            # HTTP status is already 200 after the first frame. Do not expose
            # provider errors or mistake a partial answer for a verified one.
            request.state.stream_failure_type = "AnswerGenerationFailed"
            yield _sse(
                "error",
                {
                    "code": "ANSWER_GENERATION_FAILED",
                    "message": "Answer generation is unavailable",
                },
            )

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
