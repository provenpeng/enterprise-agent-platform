"""Grounded answer orchestration and server-side citation validation."""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import aclosing

from langchain_core.embeddings import Embeddings
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.answer_generator import AnswerDraft, AnswerGenerator
from app.schemas.answer import AskResponse
from app.schemas.retrieval import SearchHit
from app.services.citations import attach_verified_citations
from app.services.errors import UpstreamUnavailable
from app.services.retrieval import search_knowledge_base

logger = logging.getLogger(__name__)
NO_ANSWER = "根据当前知识库资料，无法确定答案。"


def _abstention(knowledge_base_id: uuid.UUID) -> AskResponse:
    return AskResponse(
        knowledge_base_id=knowledge_base_id,
        answer=NO_ANSWER,
        grounded=False,
        citations=[],
    )


def _response_for_draft(
    knowledge_base_id: uuid.UUID, draft: AnswerDraft, hits: list[SearchHit]
) -> AskResponse:
    cited = attach_verified_citations(draft.answer, draft.cited_chunk_ids, hits)
    if cited is None:
        logger.info(
            "Answer abstained or contained invalid citations for %s", knowledge_base_id
        )
        return _abstention(knowledge_base_id)
    answer, citations = cited
    return AskResponse(
        knowledge_base_id=knowledge_base_id,
        answer=answer,
        grounded=True,
        citations=citations,
    )


async def retrieve_answer_hits(
    db: AsyncSession,
    embeddings: Embeddings,
    *,
    tenant_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    embedding_space_id: str,
    question: str,
    top_k: int,
    min_score: float,
    embedding_timeout_seconds: float,
) -> list[SearchHit]:
    hits = await search_knowledge_base(
        db,
        embeddings,
        tenant_id=tenant_id,
        knowledge_base_id=knowledge_base_id,
        embedding_space_id=embedding_space_id,
        query=question,
        top_k=top_k,
        min_score=min_score,
        timeout_seconds=embedding_timeout_seconds,
    )
    # Search results are DTOs; no database transaction is needed while the
    # answer model runs, and the source IDs were already tenant scoped.
    await db.rollback()
    return hits


async def answer_question(
    db: AsyncSession,
    embeddings: Embeddings,
    generator: AnswerGenerator,
    *,
    tenant_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
    embedding_space_id: str,
    question: str,
    top_k: int,
    min_score: float,
    embedding_timeout_seconds: float,
    generation_timeout_seconds: float,
) -> AskResponse:
    hits = await retrieve_answer_hits(
        db,
        embeddings,
        tenant_id=tenant_id,
        knowledge_base_id=knowledge_base_id,
        embedding_space_id=embedding_space_id,
        question=question,
        top_k=top_k,
        min_score=min_score,
        embedding_timeout_seconds=embedding_timeout_seconds,
    )
    if not hits:
        return _abstention(knowledge_base_id)

    try:
        async with asyncio.timeout(generation_timeout_seconds):
            draft = await generator.generate(question, hits)
    except Exception as exc:
        logger.warning(
            "Answer generation failed for knowledge base %s",
            knowledge_base_id,
            exc_info=True,
        )
        raise UpstreamUnavailable("Answer generation is unavailable") from exc

    return _response_for_draft(knowledge_base_id, draft, hits)


async def stream_answer(
    generator: AnswerGenerator,
    *,
    knowledge_base_id: uuid.UUID,
    question: str,
    hits: list[SearchHit],
    generation_timeout_seconds: float,
) -> AsyncIterator[str | AskResponse]:
    """Stream provisional text, then emit one answer with verified citations."""
    if not hits:
        yield _abstention(knowledge_base_id)
        return
    draft: AnswerDraft | None = None
    try:
        async with asyncio.timeout(generation_timeout_seconds):
            async with aclosing(generator.stream(question, hits)) as updates:
                async for update in updates:
                    if isinstance(update, AnswerDraft):
                        if draft is not None:
                            raise ValueError(
                                "Answer model returned multiple final drafts"
                            )
                        draft = update
                    elif isinstance(update, str) and draft is None:
                        if update:
                            yield update
                    else:
                        raise ValueError(
                            "Answer model returned an invalid stream update"
                        )
        if draft is None:
            raise ValueError("Answer model did not return a final draft")
    except Exception as exc:
        logger.warning(
            "Answer streaming failed for knowledge base %s",
            knowledge_base_id,
            exc_info=True,
        )
        raise UpstreamUnavailable("Answer generation is unavailable") from exc
    yield _response_for_draft(knowledge_base_id, draft, hits)
